from __future__ import annotations

import hmac
import hashlib
import time
from decimal import Decimal
from typing import Any, Iterable

import requests
from django.conf import settings

from app_market.models.exchange import Exchange
from app_market.providers.base import UnifiedProviderBase, ProviderRow
from app_market.providers.http import SESSION
from app_market.providers.numeric import (
    D, U, B, disp, json_safe,
    stable_set, memo_required_set,
    get_any_enabled_keys,
)

BYBIT_BASE = "https://api.bybit.com"
COIN_INFO_URL = f"{BYBIT_BASE}/v5/asset/coin/query-info"
RECV_WINDOW = int(getattr(settings, "BYBIT_RECV_WINDOW", 5000))  # мс


def _bybit_pct_to_percent(v: Any) -> Decimal:
    # Bybit отдаёт долю (например 0.001), нам нужны проценты (0.1)
    return D(v) * Decimal("100")


class BybitAdapter(UnifiedProviderBase):
    code = "BYBIT"
    _exchange: Exchange | None = None

    def provider_name_for_status(self) -> str:
        return "Bybit"

    def sync_assets(
        self, exchange: Exchange, *, timeout: int = 20, limit: int = 0, reconcile: bool = True, verbose: bool = False
    ):
        self._exchange = exchange
        try:
            return super().sync_assets(exchange=exchange, timeout=timeout, limit=limit, reconcile=reconcile, verbose=verbose)
        finally:
            self._exchange = None

    def fetch_payload(self, *, timeout: int) -> list[dict]:
        if not self._exchange:
            raise RuntimeError("Bybit: не назначена биржа для адаптера")
        api_key, api_secret = get_any_enabled_keys(self._exchange)
        if not api_key or not api_secret:
            raise RuntimeError("Bybit: нет активных API-ключей")

        ts = str(int(time.time() * 1000))
        query = ""  # у этого эндпоинта без параметров
        prehash = ts + api_key + str(RECV_WINDOW) + query
        sign = hmac.new(api_secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).hexdigest()

        headers = {
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": str(RECV_WINDOW),
            "X-BAPI-SIGN": sign,
            "X-BAPI-SIGN-TYPE": "2",
        }

        resp = SESSION.get(COIN_INFO_URL, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, dict):
            return []
        if int(data.get("retCode", -1)) != 0:
            raise requests.HTTPError(
                f"Bybit API error: retCode={data.get('retCode')} retMsg={data.get('retMsg')}",
                response=resp,
            )

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

            if not chains:
                yield ProviderRow(
                    asset_code=sym,
                    asset_name=asset_name,
                    chain_code="",
                    chain_name="",
                    AD=False, AW=False,
                    conf_dep=0, conf_wd=0,
                    dep_min=D(0), dep_max=D(0),
                    wd_min=D(0), wd_max=remain_amount if remain_amount > 0 else D(0),
                    dep_fee_pct=D(0), dep_fee_fix=D(0),
                    wd_fee_pct=D(0), wd_fee_fix=D(0),
                    requires_memo=False,
                    amount_precision=8,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    raw_meta={"coin": json_safe(item)},
                )
                continue

            for ch in chains:
                chain_code = U(ch.get("chain")) or "NATIVE"
                chain_disp = disp(ch.get("chainType")) or chain_code

                api_dep = B(ch.get("chainDeposit"))
                api_wd = B(ch.get("chainWithdraw"))

                dep_conf = int(ch.get("confirmation") or 0)
                wd_conf = int(ch.get("safeConfirmNumber") or dep_conf)

                dep_min = D(ch.get("depositMin") or 0)
                dep_max = D(0)
                wd_min = D(ch.get("withdrawMin") or 0)
                wd_max = remain_amount if remain_amount > 0 else D(0)

                wd_fee_raw = ch.get("withdrawFee")
                wd_fee_fix = D(wd_fee_raw or 0)
                wd_fee_pct = _bybit_pct_to_percent(ch.get("withdrawPercentageFee") or 0)

                # Bybit: нет фикс. комиссии — считаем, что вывод закрыт
                if wd_fee_raw in (None, "", 0, "0"):
                    api_wd = False

                requires_memo = (chain_code in memo_chains) or (U(chain_disp) in memo_chains)
                amount_precision = int(ch.get("minAccuracy") or 8)

                yield ProviderRow(
                    asset_code=sym,
                    asset_name=asset_name,
                    chain_code=chain_code,
                    chain_name=chain_disp,
                    AD=api_dep,
                    AW=api_wd,
                    conf_dep=dep_conf,
                    conf_wd=wd_conf,
                    dep_min=dep_min,
                    dep_max=dep_max,
                    wd_min=wd_min,
                    wd_max=wd_max,
                    dep_fee_pct=D(0),
                    dep_fee_fix=D(0),
                    wd_fee_pct=wd_fee_pct,
                    wd_fee_fix=wd_fee_fix,
                    requires_memo=requires_memo,
                    amount_precision=amount_precision,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    raw_meta={"coin": json_safe(item)},
                )
