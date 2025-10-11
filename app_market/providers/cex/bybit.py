from __future__ import annotations

import json
import time
import hmac
import hashlib
from decimal import Decimal
from typing import Any, Iterable, Dict
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from app_market.models.exchange import Exchange
from app_market.providers.base import UnifiedProviderBase, ProviderRow
from app_market.providers.numeric import (
    UA, D, U, B, disp, json_safe,
    stable_set, memo_required_set,
    get_any_enabled_keys
)

BYBIT_BASE = "https://api.bybit.com"
COIN_INFO_URL = f"{BYBIT_BASE}/v5/asset/coin/query-info"
RECV_WINDOW = "5000"


def _bybit_pct_to_percent(v: Any) -> Decimal:
    # Bybit отдаёт долю (например 0.001), нам нужны проценты (0.1)
    return D(v) * Decimal("100")


def _http_get_json(url: str, headers: Dict[str, str], *, timeout: int = 20, retries: int = 3) -> Any:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(0.3 * (3 ** attempt))
    assert last_err is not None
    raise last_err


class BybitAdapter(UnifiedProviderBase):
    code = "BYBIT"

    # --- доступ к ключам текущей биржи (устанавливается в sync_assets базового класса) ---
    _exchange: Exchange | None = None

    def provider_name_for_status(self) -> str:
        return "Bybit"

    # --- тонкая часть: запрос и маппинг в ProviderRow ---

    def fetch_payload(self, *, timeout: int) -> list[dict]:
        if not self._exchange:
            raise RuntimeError("Bybit: не назначена биржа для адаптера")
        api_key, api_secret = get_any_enabled_keys(self._exchange)
        if not api_key or not api_secret:
            raise RuntimeError("Bybit: нет активных API-ключей")

        ts = str(int(time.time() * 1000))
        query = ""  # у этого эндпоинта без параметров
        prehash = ts + api_key + RECV_WINDOW + query
        sign = hmac.new(api_secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {
            "User-Agent": UA,
            "Accept": "application/json",
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
            "X-BAPI-SIGN": sign,
            "X-BAPI-SIGN-TYPE": "2",
        }

        data = _http_get_json(COIN_INFO_URL, headers, timeout=timeout, retries=3)
        if not isinstance(data, dict):
            return []
        if int(data.get("retCode", -1)) != 0:
            raise RuntimeError(f"Bybit API error: retCode={data.get('retCode')} retMsg={data.get('retMsg')}")
        result = data.get("result") or {}
        rows = result.get("rows") or []
        return list(rows) if isinstance(rows, list) else []

    def iter_rows(self, payload: list[dict]) -> Iterable[ProviderRow]:
        stables = stable_set()
        memo_chains = memo_required_set()

        for item in payload:
            sym = U(item.get("coin"))
            if not sym:
                continue
            asset_name = disp(item.get("name")) or sym
            remain_amount = D(item.get("remainAmount"))
            chains = item.get("chains") or []

            # без сетей — базовый конвейер решит: FIAT/NOTDEFINED и установит AD/AW
            if not chains:
                yield ProviderRow(
                    asset_code=sym,
                    asset_name=asset_name,
                    chain_code="",  # важно: пусто => «без сетей»
                    chain_name="",
                    AD=False, AW=False,  # неважно — база перезапишет
                    conf_dep=0, conf_wd=0,
                    dep_min=D(0), dep_max=D(0),
                    wd_min=D(0), wd_max=remain_amount if remain_amount > 0 else D(0),
                    dep_fee_pct=D(0), dep_fee_fix=D(0),
                    wd_fee_pct=D(0), wd_fee_fix=D(0),
                    requires_memo=False,
                    amount_precision=8,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    raw_meta={"coin": json_safe(item)},  # только корневой объект
                )
                continue

            for ch in chains:
                chain_code = U(ch.get("chain")) or "NATIVE"
                chain_disp = disp(ch.get("chainType")) or chain_code

                # «как заявлено API» (до учёта подтверждений)
                api_dep = B(ch.get("chainDeposit"))
                api_wd = B(ch.get("chainWithdraw"))

                # подтверждения (депозит/вывод)
                dep_conf = int(ch.get("confirmation") or 0)
                wd_conf = int(ch.get("safeConfirmNumber") or dep_conf)

                dep_min = D(ch.get("depositMin") or 0)
                dep_max = D(0)  # нет явного поля в API
                wd_min = D(ch.get("withdrawMin") or 0)
                wd_max = remain_amount if remain_amount > 0 else D(0)

                wd_fee_raw = ch.get("withdrawFee")
                wd_fee_fix = D(wd_fee_raw or 0)
                wd_fee_pct = _bybit_pct_to_percent(ch.get("withdrawPercentageFee") or 0)

                # частное правило Bybit: если нет фикс. комиссии в ответе — считаем, что вывод закрыт
                if wd_fee_raw in (None, "", 0, "0"):
                    api_wd = False

                requires_memo = (chain_code in memo_chains) or (U(chain_disp) in memo_chains)
                amount_precision = int(ch.get("minAccuracy") or 8)

                yield ProviderRow(
                    asset_code=sym,
                    asset_name=asset_name,
                    chain_code=chain_code,  # наличие сети => база классифицирует как CRYPTO
                    chain_name=chain_disp,
                    AD=bool(api_dep),
                    AW=bool(api_wd),
                    conf_dep=int(dep_conf),
                    conf_wd=int(wd_conf),
                    dep_min=dep_min,
                    dep_max=dep_max,
                    wd_min=wd_min,
                    wd_max=wd_max,
                    dep_fee_pct=D(0),
                    dep_fee_fix=D(0),
                    wd_fee_pct=wd_fee_pct,
                    wd_fee_fix=wd_fee_fix,
                    requires_memo=bool(requires_memo),
                    amount_precision=amount_precision,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    raw_meta={"coin": json_safe(item)},  # только корневой объект
                )

    # --- хук: прокинуть exchange внутрь fetch_payload ---
    def sync_assets(self, exchange: Exchange, *, timeout: int = 20, limit: int = 0, reconcile: bool = True, verbose: bool = False):
        self._exchange = exchange
        try:
            return super().sync_assets(exchange=exchange, timeout=timeout, limit=limit, reconcile=reconcile, verbose=verbose)
        finally:
            self._exchange = None

    # --- вспомогательное: взять любые активные ключи ---
    def _get_any_keys(self, exchange: Exchange) -> tuple[str | None, str | None]:
        try:
            keys = exchange.keys.filter(is_enabled=True).order_by("-id").first()
            if not keys:
                return (None, None)
            return (keys.api_key or None, keys.api_secret or None)
        except Exception:
            return (None, None)
