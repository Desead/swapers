from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from app_market.models.exchange import Exchange
from app_market.providers.base import UnifiedProviderBase, ProviderRow
from app_market.providers.numeric import (
    UA, D, U, B, disp, json_safe,
    stable_set, memo_required_set,
    get_any_enabled_keys,
)

WB_BASE = "https://whitebit.com"
ASSETS_URL = f"{WB_BASE}/api/v4/public/assets"
FEE_URL = f"{WB_BASE}/api/v4/public/fee"
PRIV_FEE_PATH = "/api/v4/main-account/fee"
PRIV_FEE_URL = f"{WB_BASE}{PRIV_FEE_PATH}"


# ---------------- HTTP helpers ----------------

def _http_get_json(url: str, timeout: int = 20, retries: int = 3) -> Any:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(0.4 * (2 ** attempt))
    raise RuntimeError(f"WhiteBIT: ошибка запросов: {last_exc}")


def _http_post_signed_json(url: str, body: dict, api_key: str, api_secret: str, timeout: int = 30, retries: int = 3) -> Any:
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    b64 = base64.b64encode(payload)
    sign = hmac.new(api_secret.encode("utf-8"), b64, hashlib.sha512).hexdigest()

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(
                url,
                data=payload,
                headers={
                    "User-Agent": UA,
                    "Content-Type": "application/json",
                    "X-TXC-APIKEY": api_key,
                    "X-TXC-PAYLOAD": b64.decode("ascii"),
                    "X-TXC-SIGNATURE": sign,
                },
                method="POST",
            )
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(0.4 * (2 ** attempt))
    raise RuntimeError(f"WhiteBIT: ошибка запросов (priv fee): {last_exc}")


# ---------------- Fee parsing ----------------

def _flex_percent(v: Any) -> Decimal:
    if isinstance(v, dict):
        return D(v.get("percent"))
    return D(v)


class _FeeSide:
    __slots__ = ("min_amount", "max_amount", "fixed", "percent")

    def __init__(self, min_amount: Decimal, max_amount: Decimal, fixed: Decimal, percent: Decimal):
        self.min_amount = min_amount
        self.max_amount = max_amount
        self.fixed = fixed
        self.percent = percent


class _FeePack:
    __slots__ = ("deposit", "withdraw")

    def __init__(self, deposit: _FeeSide, withdraw: _FeeSide):
        self.deposit = deposit
        self.withdraw = withdraw


def _parse_public_fee(obj: dict) -> Dict[Tuple[str, Optional[str]], _FeePack]:
    """
    Ключи типа "USDT (TRC20)" | "BTC", значения с полями deposit/withdraw.
    Вернём карту {(ticker, network|None) -> _FeePack}
    """
    out: Dict[Tuple[str, Optional[str]], _FeePack] = {}
    for key, row in obj.items():
        if not isinstance(row, dict):
            continue
        m = re.match(r"^\s*([A-Za-z0-9]+)\s*(?:\(\s*([^)]+)\s*\))?\s*$", str(key))
        ticker = (m.group(1) if m else str(key)).strip().upper()
        network = (m.group(2).strip().upper() if (m and m.group(2)) else None)

        dep = row.get("deposit") or {}
        wd = row.get("withdraw") or {}

        out[(ticker, network)] = _FeePack(
            deposit=_FeeSide(
                min_amount=D(dep.get("min_amount")),
                max_amount=D(dep.get("max_amount")),
                fixed=D(dep.get("fixed")),
                percent=_flex_percent(dep.get("flex")),
            ),
            withdraw=_FeeSide(
                min_amount=D(wd.get("min_amount")),
                max_amount=D(wd.get("max_amount")),
                fixed=D(wd.get("fixed")),
                percent=_flex_percent(wd.get("flex")),
            ),
        )
    return out


def _fetch_private_fee(exchange: Exchange, *, timeout: int = 30) -> Dict[str, dict]:
    """
    Приватные комиссии возвращаются списком по тикерам (без сетей).
    Вернём карту {TICKER -> row}.
    """
    api_key, api_secret = get_any_enabled_keys(exchange)
    if not api_key or not api_secret:
        return {}
    body = {"request": PRIV_FEE_PATH, "nonce": int(time.time() * 1000)}
    data = _http_post_signed_json(PRIV_FEE_URL, body, api_key, api_secret, timeout=timeout)
    out: Dict[str, dict] = {}
    if isinstance(data, list):
        for row in data:
            t = U(row.get("ticker"))
            if t:
                out[t] = row
    return out


def _merge_fee_for(ticker: str, network: Optional[str], pub: Dict[Tuple[str, Optional[str]], _FeePack], priv: Dict[str, dict]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """
    Возвращает (dep_pct, dep_fix, wd_pct, wd_fix).
    Приоритет: приватные по тикеру -> публичные по (ticker,net) -> публичные по (ticker,None) -> нули.
    """
    if ticker in priv:
        d = priv[ticker].get("deposit") or {}
        w = priv[ticker].get("withdraw") or {}
        return (
            D(d.get("percentFlex")), D(d.get("fixed")),
            D(w.get("percentFlex")), D(w.get("fixed")),
        )
    pack = pub.get((ticker, network)) or pub.get((ticker, None))
    if pack:
        return (
            pack.deposit.percent, pack.deposit.fixed,
            pack.withdraw.percent, pack.withdraw.fixed,
        )
    return (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))


# ---------------- Adapter ----------------

class WhitebitAdapter(UnifiedProviderBase):
    code = "WHITEBIT"
    _exchange: Exchange | None = None  # нужен для приватных комиссий

    def provider_name_for_status(self) -> str:
        return "WhiteBIT"

    # Прокидываем ссылку на exchange внутрь fetch_payload (для приватных комиссий)
    def sync_assets(self, exchange: Exchange, *, timeout: int = 20, limit: int = 0, reconcile: bool = True, verbose: bool = False):
        self._exchange = exchange
        try:
            return super().sync_assets(exchange=exchange, timeout=timeout, limit=limit, reconcile=reconcile, verbose=verbose)
        finally:
            self._exchange = None

    def fetch_payload(self, *, timeout: int) -> dict:
        assets_json = _http_get_json(ASSETS_URL, timeout=timeout)
        fee_json = _http_get_json(FEE_URL, timeout=timeout)
        priv_fee_map: Dict[str, dict] = {}
        if self._exchange is not None:
            try:
                priv_fee_map = _fetch_private_fee(self._exchange, timeout=timeout)
            except Exception:
                priv_fee_map = {}
        return {"assets": assets_json, "fee_pub": fee_json, "fee_priv": priv_fee_map}

    def iter_rows(self, payload: dict) -> Iterable[ProviderRow]:
        stables = stable_set()
        memo_set = memo_required_set()

        assets_json = payload.get("assets") or {}
        fee_json = payload.get("fee_pub") or {}
        priv_fee_map = payload.get("fee_priv") or {}

        pub_fee_map = _parse_public_fee(fee_json)

        for ticker, meta in assets_json.items():
            if not isinstance(meta, dict):
                continue
            t = U(ticker)
            if not t:
                continue

            name = disp(meta.get("name")) or t
            precision = int(meta.get("currency_precision") or 8)

            # WhiteBIT: фиатные шлюзы имеют providers и нет confirmations (или они пустые/0)
            providers = meta.get("providers") or {}
            confirmations = meta.get("confirmations", None)  # может быть int или dict
            no_confirmations = (
                confirmations in (None, "", 0, {})
            )

            # сети/лимиты
            networks = meta.get("networks") or {}
            nets_dep = set(networks.get("deposits") or [])
            nets_wd = set(networks.get("withdraws") or [])
            lims = meta.get("limits") or {}
            lim_dep: dict = lims.get("deposit") or {}
            lim_wd: dict = lims.get("withdraw") or {}

            # Глобальные флаги
            can_dep_global = B(meta.get("can_deposit"))
            can_wd_global = B(meta.get("can_withdraw"))
            requires_memo_flag = B(meta.get("is_memo"))

            # --- FIAT по специфике WhiteBIT ---
            # Есть providers И нет подтверждений -> считаем как фиатный шлюз (без сетей).
            if providers and no_confirmations:
                dep_pct, dep_fix, wd_pct, wd_fix = _merge_fee_for(t, None, pub_fee_map, priv_fee_map)

                dep_min = D(meta.get("min_deposit"))
                dep_max = D(meta.get("max_deposit"))
                wd_min = D(meta.get("min_withdraw"))
                wd_max = D(meta.get("max_withdraw"))

                yield ProviderRow(
                    asset_code=t,
                    asset_name=name,
                    chain_code="",          # без сетей — базовый конвейер определит FIAT/NOTDEFINED
                    chain_name="",
                    AD=bool(can_dep_global),  # база всё равно перезапишет для FIAT в True/True
                    AW=bool(can_wd_global),
                    conf_dep=0,
                    conf_wd=0,
                    dep_min=dep_min,
                    dep_max=dep_max,
                    wd_min=wd_min,
                    wd_max=wd_max,
                    dep_fee_pct=dep_pct,
                    dep_fee_fix=dep_fix,
                    wd_fee_pct=wd_pct,
                    wd_fee_fix=wd_fix,
                    requires_memo=False,
                    amount_precision=precision,
                    is_stable=(t in stables),
                    raw_meta={"assets": json_safe(meta)},  # только корневой объект
                )
                continue

            # --- CRYPTO (по сетям/лимитам/подтверждениям) ---
            # Список всех встреченных сетей из deposit/withdraw/confirmations/limits
            confirms_map = confirmations if isinstance(confirmations, dict) else {}
            nets_all = sorted(
                set(nets_dep) | set(nets_wd) | set(confirms_map.keys()) | set(lim_dep.keys()) | set(lim_wd.keys())
            )

            if not nets_all:
                # Без сетей и не распознали как фиат — NOTDEFINED (база присвоит)
                yield ProviderRow(
                    asset_code=t,
                    asset_name=name,
                    chain_code="",       # важно: пусто => «без сетей»
                    chain_name="",
                    AD=False, AW=False,  # база перезапишет для NOTDEFINED в False/False
                    conf_dep=0, conf_wd=0,
                    dep_min=D(0), dep_max=D(0),
                    wd_min=D(0), wd_max=D(0),
                    dep_fee_pct=D(0), dep_fee_fix=D(0),
                    wd_fee_pct=D(0), wd_fee_fix=D(0),
                    requires_memo=False,
                    amount_precision=precision,
                    is_stable=(t in stables),
                    raw_meta={"assets": json_safe(meta)},
                )
                continue

            for net in nets_all:
                net_u = str(net).strip().upper()

                # «как заявлено API» на уровне сети
                dep_ok = bool(can_dep_global and (not nets_dep or net in nets_dep))
                wd_ok  = bool(can_wd_global and (not nets_wd or net in nets_wd))

                # подтверждения общие на сеть
                conf = int((confirms_map or {}).get(net) or 0)

                # лимиты по сети
                dep_limits = (lim_dep.get(net) or {})
                wd_limits = (lim_wd.get(net) or {})
                dep_min = D(dep_limits.get("min"))
                dep_max = D(dep_limits.get("max"))
                wd_min = D(wd_limits.get("min"))
                wd_max = D(wd_limits.get("max"))

                dep_pct, dep_fix, wd_pct, wd_fix = _merge_fee_for(t, net_u, pub_fee_map, priv_fee_map)

                requires_memo = bool(requires_memo_flag or (U(net_u) in memo_set))

                yield ProviderRow(
                    asset_code=t,
                    asset_name=name,
                    chain_code=net_u,           # наличие сети => база классифицирует как CRYPTO
                    chain_name=net_u,
                    AD=dep_ok,
                    AW=wd_ok,
                    conf_dep=conf,
                    conf_wd=conf,               # отдельного для вывода нет — используем общий
                    dep_min=dep_min,
                    dep_max=dep_max,
                    wd_min=wd_min,
                    wd_max=wd_max,
                    dep_fee_pct=dep_pct,
                    dep_fee_fix=dep_fix,
                    wd_fee_pct=wd_pct,
                    wd_fee_fix=wd_fix,
                    requires_memo=requires_memo,
                    amount_precision=precision,
                    is_stable=(t in stables),
                    raw_meta={"assets": json_safe(meta)},  # только корневой объект
                )
