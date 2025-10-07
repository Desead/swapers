# app_market/management/commands/mexc_export_clean_csv.py
from __future__ import annotations

import csv
import hmac
import hashlib
import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from typing import Any, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError

# === Decimal context: безопасная точность без экспонент ===
getcontext().prec = 50

UA = "swapers-sync/1.0 (+https://github.com/Desead/swapers)"
BASE = "https://api.mexc.com"  # v3 spot private

# Полностью синхронизировано с провайдером MEXC:
_BIGNUM = Decimal("1e20")      # «потолок» для сумм/лимитов/фикс.комиссий (как в адаптере)
_ZERO = Decimal("0")

# Квантуем как в адаптере:
# - суммы/лимиты/фикс.комиссии: 10 знаков
# - проценты: 5 знаков, но не более 100
_Q_AMT = Decimal("0.0000000001")  # 10 знаков
_Q_PCT = Decimal("0.00001")       # 5 знаков


@dataclass
class CleanRow:
    asset_code: str
    asset_name: str
    chain_code: str
    chain_name: str
    is_fiat: bool
    D: bool
    W: bool
    AD: bool
    AW: bool
    confirmations_deposit: int
    confirmations_withdraw: int
    deposit_min: Decimal
    deposit_max: Decimal
    withdraw_min: Decimal
    withdraw_max: Decimal
    deposit_fee_percent: Decimal
    withdraw_fee_percent: Decimal
    withdraw_fee_fixed: Decimal
    requires_memo: bool
    amount_precision: int


# ---------- Помощники (идентичны по смыслу провайдеру) ----------
def _dec_ok(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, (int, float, Decimal)):
        return True
    s = str(v).strip()
    if not s:
        return False
    up = s.upper()
    return up not in {"NAN", "INF", "+INF", "-INF", "INFINITY", "+INFINITY", "-INFINITY"}


def _q_amt(v: Any, places: int = 10) -> Decimal:
    """
    Нормализуем «суммовые» величины (мин/макс/фикс.комиссии):
    - None/пусто/NaN/Inf → 0
    - отрицательные → берём модуль (как в адаптере)
    - кап по модулю 1e20
    - квантуем до places (по умолчанию 10 знаков), ROUND_DOWN
    """
    try:
        if not _dec_ok(v):
            return _ZERO
        d = Decimal(str(v))
        if d.is_nan() or d.is_infinite():
            return _ZERO
        if d < 0:
            d = -d
        if d > _BIGNUM:
            d = _BIGNUM
        q = Decimal(1).scaleb(-places)  # 10 знаков по умолчанию
        return d.quantize(q, rounding=ROUND_DOWN)
    except InvalidOperation:
        return _ZERO


def _q_pct(v: Any, places: int = 5) -> Decimal:
    """
    Проценты: квантуем и ограничиваем сверху 100%.
    Отрицательные трактуются как 0 (через модуль в _q_amt).
    """
    d = _q_amt(v, places=places)
    return Decimal("100") if d > Decimal("100") else d


# -------------------- Подписанный GET (без Content-Type!) -------------------
def _http_signed_get(path: str, api_key: str, api_secret: str, timeout: int = 15, verbose: bool = False) -> Any:
    ts = int(time.time() * 1000)
    params = {"timestamp": str(ts), "recvWindow": "20000"}
    query = urlencode(params)
    sig = hmac.new(api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

    url = f"{BASE}{path}?{query}&signature={sig}"
    headers = {
        "User-Agent": UA,
        "X-MEXC-APIKEY": api_key,
        # ВАЖНО: не ставим Content-Type для GET (иначе 400 Invalid content Type)
    }
    if verbose:
        print(f"[MEXC][SIGN] path={path}")
        print(f"[MEXC][SIGN] pre-sign='{query}'")
        print(f"[MEXC][SIGN] sig={sig[:8]}…{sig[-8:]} ts={ts}")

    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except HTTPError as e:
        reason = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
        raise CommandError(f"MEXC: HTTP {e.code}: {reason}")
    except URLError as e:
        raise CommandError(f"MEXC: URLError: {e.reason}")

    try:
        return json.loads(body.decode("utf-8"))
    except Exception as e:
        raise CommandError(f"MEXC: bad JSON: {e}")


# ---------------- Приведение payload → нормализованных строк ----------------
def _rows_from_mexc(payload: Any, verbose: bool = False) -> Iterable[CleanRow]:
    # payload — список "coin"-объектов с networkList
    for coin in payload or []:
        asset_code = (coin.get("coin") or coin.get("asset") or "").upper()
        if not asset_code:
            continue
        asset_name = (coin.get("name") or coin.get("fullName") or asset_code) or asset_code

        networks = coin.get("networkList") or coin.get("chains") or []
        is_fiat = False
        if not isinstance(networks, list) or not networks:
            # нет сетей — считаем фиатом для целей экспорта
            is_fiat = True
            networks = [{"network": "FIAT", "name": "FIAT"}]

        for nw in networks:
            chain_code = str(nw.get("network") or nw.get("chain") or nw.get("name") or "").upper()
            if not chain_code:
                continue
            chain_name = str(nw.get("name") or chain_code)

            dep_enable = bool(nw.get("depositEnable") or nw.get("canDeposit") or False)
            wdr_enable = bool(nw.get("withdrawEnable") or nw.get("canWithdraw") or False)

            # Автофлаги в экспорте приравняем к фактическим
            AD = dep_enable
            AW = wdr_enable

            # Конфирмы: депозит — minConfirm (если крипта), вывод — не меньше депозита
            conf_dep = 0
            conf_wdr = 0
            try:
                conf_dep = int(nw.get("minConfirm") or 0)
            except Exception:
                conf_dep = 0
            try:
                conf_wdr = max(conf_dep, int(nw.get("withdrawConfirm") or 0))
            except Exception:
                conf_wdr = conf_dep

            # Числа → как в адаптере: квантуем/капаем/убираем NaN/Inf
            w_fee_fixed = _q_amt(nw.get("withdrawFee"))
            w_min = _q_amt(nw.get("withdrawMin"))
            w_max = _q_amt(nw.get("withdrawMax"))

            # Процентные комиссии у MEXC обычно отсутствуют (оставим 0, но нормализуем)
            d_fee_pct = _q_pct(nw.get("depositFeePercent"))
            w_fee_pct = _q_pct(nw.get("withdrawFeePercent"))

            d_min = _q_amt(nw.get("depositMin"))
            d_max = _q_amt(nw.get("depositMax"))

            # Требование MEMO: грубая эвристика (в бою берёте SiteSetup)
            requires_memo = str(chain_code) in {
                "XLM", "XRP", "EOS", "TON", "HBAR", "APT", "SUI", "KAVA", "BNB", "IOTA", "CFX"
            } or bool(nw.get("memoRegex"))

            amount_precision = 8
            try:
                p = nw.get("withdrawPrecision") or nw.get("precision")
                if p is not None:
                    amount_precision = int(str(p))
            except Exception:
                amount_precision = 8

            yield CleanRow(
                asset_code=asset_code,
                asset_name=asset_name,
                chain_code=chain_code,
                chain_name=chain_name,
                is_fiat=is_fiat,
                D=dep_enable, W=wdr_enable, AD=AD, AW=AW,
                confirmations_deposit=max(1 if not is_fiat else 0, conf_dep),
                confirmations_withdraw=max(1 if not is_fiat else 0, conf_wdr),
                deposit_min=d_min, deposit_max=d_max,
                withdraw_min=w_min, withdraw_max=w_max,
                deposit_fee_percent=d_fee_pct, withdraw_fee_percent=w_fee_pct,
                withdraw_fee_fixed=w_fee_fixed,
                requires_memo=requires_memo,
                amount_precision=amount_precision,
            )


class Command(BaseCommand):
    help = "Экспортирует конфигурацию депозитов/выводов MEXC в CSV (точно как очищает адаптер)."

    def add_arguments(self, parser):
        parser.add_argument("--output", "-o", default="mexc_clean.csv", help="Путь к CSV файлу.")
        parser.add_argument("--timeout", type=int, default=15)
        parser.add_argument("--verbose", action="store_true")
        parser.add_argument("--api-key", default=os.getenv("MEXC_API_KEY", ""))
        parser.add_argument("--api-secret", default=os.getenv("MEXC_API_SECRET", ""))

    def handle(self, *args, **opts):
        out_path: str = opts["output"]
        timeout: int = opts["timeout"]
        verbose: bool = opts["verbose"]
        api_key: str = 'mx0vglLnDQf1EAZcm6'
        api_secret: str = '4cd6e060aa884c07b35b265f82bf75ee'

        if not api_key or not api_secret:
            raise CommandError(
                "Укажите API-ключи: --api-key/--api-secret или переменные окружения MEXC_API_KEY/MEXC_API_SECRET."
            )

        if verbose:
            # Публичный time probe для понимания сетевой задержки
            try:
                req = Request(f"{BASE}/api/v3/time", headers={"User-Agent": UA})
                with urlopen(req, timeout=timeout) as r:
                    body = json.loads(r.read().decode("utf-8"))
                server_time = int(body.get("serverTime") or 0)
                local = int(time.time() * 1000)
                print(f"[MEXC][PROBE] serverTime={server_time} local={local} skew_ms={server_time - local}")
            except Exception as e:
                print(f"[MEXC][PROBE] time probe failed: {e}")

        data = _http_signed_get("/api/v3/capital/config/getall", api_key, api_secret, timeout=timeout, verbose=verbose)

        rows = list(_rows_from_mexc(data, verbose=verbose))
        if verbose:
            print(f"[MEXC] parsed rows: {len(rows)}")

        fieldnames = [
            "asset_code", "asset_name", "chain_code", "chain_name", "is_fiat",
            "D", "W", "AD", "AW",
            "confirmations_deposit", "confirmations_withdraw",
            "deposit_min", "deposit_max",
            "withdraw_min", "withdraw_max",
            "deposit_fee_percent", "withdraw_fee_percent",
            "withdraw_fee_fixed",
            "requires_memo",
            "amount_precision",
        ]
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                # форматируем без экспонент и без лишних знаков
                w.writerow({
                    "asset_code": r.asset_code,
                    "asset_name": r.asset_name,
                    "chain_code": r.chain_code,
                    "chain_name": r.chain_name,
                    "is_fiat": int(bool(r.is_fiat)),
                    "D": int(bool(r.D)),
                    "W": int(bool(r.W)),
                    "AD": int(bool(r.AD)),
                    "AW": int(bool(r.AW)),
                    "confirmations_deposit": r.confirmations_deposit,
                    "confirmations_withdraw": r.confirmations_withdraw,
                    "deposit_min": f"{r.deposit_min:f}",
                    "deposit_max": f"{r.deposit_max:f}",
                    "withdraw_min": f"{r.withdraw_min:f}",
                    "withdraw_max": f"{r.withdraw_max:f}",
                    "deposit_fee_percent": f"{r.deposit_fee_percent:f}",
                    "withdraw_fee_percent": f"{r.withdraw_fee_percent:f}",
                    "withdraw_fee_fixed": f"{r.withdraw_fee_fixed:f}",
                    "requires_memo": int(bool(r.requires_memo)),
                    "amount_precision": r.amount_precision,
                })

        self.stdout.write(self.style.SUCCESS(f"Готово: записано {len(rows)} строк в {out_path}"))
