from __future__ import annotations

import hmac
import hashlib
import json
import time
from decimal import Decimal
from typing import Any, Iterable, Dict, Tuple, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from app_market.models.exchange import Exchange
from app_market.providers.base import UnifiedProviderBase, ProviderRow
from app_market.providers.numeric import (
    UA, D, U, B, disp, json_safe,
    stable_set, memo_required_set,
    get_any_enabled_keys,
)

BASE = "https://api.mexc.com"
CAPITAL_CONFIG_URL = "/api/v3/capital/config/getall"
RECV_WINDOW = 20000


# ---------------- HTTP ----------------

def _mexc_sign(secret: str, query: str) -> str:
    return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()


def _http_get_json_signed(path: str, api_key: str, api_secret: str, *, timeout: int = 20, retries: int = 2) -> Any:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            ts = int(time.time() * 1000)
            qs = urlencode({"timestamp": ts, "recvWindow": RECV_WINDOW})
            sig = _mexc_sign(api_secret, qs)
            url = f"{BASE}{path}?{qs}&signature={sig}"

            req = Request(url, headers={"User-Agent": UA, "X-MEXC-APIKEY": api_key})
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(0.4 * (attempt + 1))
    assert last_err is not None
    raise RuntimeError(f"MEXC: ошибка запросов: {last_err}")


def _unwrap(payload: Any) -> List[dict]:
    """Аккуратно разворачиваем ответ MEXC (лист или обёртка с data/result/rows)."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        # успешные варианты
        for k in ("data", "result", "rows"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
        # если есть code/msg — проверим на ошибку
        code = payload.get("code")
        msg = payload.get("msg") or payload.get("message") or ""
        if code not in (None, 0, "0", 200, "200"):
            raise RuntimeError(f"MEXC API error: code={code} msg={msg}")
        return []
    return []


# ---------------- Adapter ----------------

class MexcAdapter(UnifiedProviderBase):
    code = "MEXC"
    _exchange: Exchange | None = None

    def provider_name_for_status(self) -> str:
        return "MEXC"

    # Для MEXC withdraw_max не пишем — их цифры часто «мусорные»
    def policy_write_withdraw_max(self) -> bool:
        return False

    # Прокидываем exchange в fetch_payload
    def sync_assets(self, exchange: Exchange, *, timeout: int = 20, limit: int = 0, reconcile: bool = True, verbose: bool = False):
        self._exchange = exchange
        try:
            return super().sync_assets(exchange=exchange, timeout=timeout, limit=limit, reconcile=reconcile, verbose=verbose)
        finally:
            self._exchange = None

    # --- тонкая часть: запрос и маппинг в ProviderRow ---

    def fetch_payload(self, *, timeout: int) -> list[dict]:
        if not self._exchange:
            raise RuntimeError("MEXC: не назначена биржа для адаптера")
        api_key, api_secret = get_any_enabled_keys(self._exchange)
        if not api_key or not api_secret:
            raise RuntimeError("MEXC: не найдены активные API-ключи для этого провайдера")
        data = _http_get_json_signed(CAPITAL_CONFIG_URL, api_key, api_secret, timeout=timeout, retries=2)
        return _unwrap(data)

    def iter_rows(self, payload: list[dict]) -> Iterable[ProviderRow]:
        stables = stable_set()
        memo_chains = memo_required_set()

        for entry in payload:
            if not isinstance(entry, dict):
                continue

            # Корневой объект монеты:
            #  - обычно это сам entry (где entry["coin"] — строка кода),
            #  - но иногда встречается обёртка {"coin": {...}, "chain": {...}} — тогда берём вложенный dict.
            coin_field = entry.get("coin")
            if isinstance(coin_field, dict):
                root = coin_field
            else:
                root = entry

            sym = U(root.get("coin") or root.get("asset"))
            if not sym:
                continue
            asset_name = disp(root.get("name") or root.get("fullName") or sym)

            networks = root.get("networkList") or root.get("chains") or []
            if not isinstance(networks, list) or len(networks) == 0:
                # без сетей — базовый конвейер сам решит FIAT/NOTDEFINED и выставит AD/AW
                yield ProviderRow(
                    asset_code=sym,
                    asset_name=asset_name,
                    chain_code="",  # важно: пусто => «без сетей»
                    chain_name="",
                    AD=False, AW=False,           # для безсетевых база перезапишет
                    conf_dep=0, conf_wd=0,
                    dep_min=D(0), dep_max=D(0),
                    wd_min=D(0), wd_max=D(0),
                    dep_fee_pct=D(0), dep_fee_fix=D(0),
                    wd_fee_pct=D(0), wd_fee_fix=D(0),
                    requires_memo=False,
                    amount_precision=8,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    raw_meta={"coin": json_safe(root)},  # только корневой объект
                )
                continue

            for net in networks:
                if not isinstance(net, dict):
                    continue
                chain_code = U(net.get("network") or net.get("netWork") or net.get("chain") or net.get("name"))
                if not chain_code:
                    continue
                chain_name = disp(net.get("name") or net.get("network") or chain_code)

                # «как заявлено API» (до учёта подтверждений)
                api_dep_on = B(net.get("depositEnable"), net.get("canDeposit"))
                api_wd_on  = B(net.get("withdrawEnable"), net.get("canWithdraw"))

                # Подтверждения: если для вывода нет отдельного — берём депозитные
                dep_conf = int((net.get("minConfirm") or net.get("confirmTimes") or 0) or 0)
                wd_conf  = int((net.get("withdrawConfirm") or net.get("withdrawConfirmTimes") or dep_conf) or 0)

                # Лимиты
                dep_min = D(net.get("depositMin"))
                dep_max = D(net.get("depositMax"))
                wd_min  = D(net.get("withdrawMin"))
                wd_max  = D(net.get("withdrawMax"))

                # Комиссии
                wd_fee_fix = D(net.get("withdrawFee"))
                wd_fee_pct = D(net.get("withdrawFeePercent") or 0)
                dep_fee_fix = D(net.get("depositFee") or net.get("depositFeeFixed") or 0)
                dep_fee_pct = D(net.get("depositFeePercent") or 0)

                # Memo/tag
                requires_memo = B(net.get("needTag"))
                if not requires_memo:
                    tips = (disp(net.get("specialTips") or "")).lower()
                    if "memo" in tips or "tag" in tips:
                        requires_memo = True
                if not requires_memo and (chain_code in memo_chains or U(chain_name) in memo_chains):
                    requires_memo = True

                # Точность
                amount_precision = int((net.get("withdrawPrecision") or net.get("accuracy") or 8) or 8)

                yield ProviderRow(
                    asset_code=sym,
                    asset_name=asset_name,
                    chain_code=chain_code,   # наличие сети => база классифицирует как CRYPTO
                    chain_name=chain_name,
                    AD=bool(api_dep_on),
                    AW=bool(api_wd_on),
                    conf_dep=dep_conf,
                    conf_wd=wd_conf,
                    dep_min=dep_min,
                    dep_max=dep_max,
                    wd_min=wd_min,
                    wd_max=wd_max,
                    dep_fee_pct=dep_fee_pct,
                    dep_fee_fix=dep_fee_fix,
                    wd_fee_pct=wd_fee_pct,
                    wd_fee_fix=wd_fee_fix,
                    requires_memo=bool(requires_memo),
                    amount_precision=amount_precision,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    raw_meta={"coin": json_safe(root)},  # только корневой объект
                )
