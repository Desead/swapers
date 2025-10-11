from __future__ import annotations

from typing import Any, Iterable
import requests

from app_market.providers.base import UnifiedProviderBase, ProviderRow
from app_market.providers.http import SESSION
from app_market.providers.numeric import (
    D, U, B, disp, json_safe,
    stable_set, memo_required_set,
)

KU_BASE = "https://api.kucoin.com"
CURRENCY_URL = f"{KU_BASE}/api/v3/currencies"


class KucoinAdapter(UnifiedProviderBase):
    code = "KUCOIN"

    def provider_name_for_status(self) -> str:
        return "KuCoin"

    def fetch_payload(self, *, timeout: int) -> list[dict]:
        resp = SESSION.get(CURRENCY_URL, timeout=timeout)
        resp.raise_for_status()
        data: Any = resp.json()
        if not isinstance(data, dict) or data.get("code") != "200000":
            return []
        return list(data.get("data") or [])

    def iter_rows(self, payload: list[dict]) -> Iterable[ProviderRow]:
        stables = stable_set()
        memo_chains = memo_required_set()

        for item in payload:
            sym = U(item.get("currency"))
            if not sym:
                continue
            asset_name = disp(item.get("fullName")) or sym
            amount_precision_root = int(item.get("precision") or 8)

            chains = item.get("chains") or []
            if not isinstance(chains, list) or len(chains) == 0:
                yield ProviderRow(
                    asset_code=sym,
                    asset_name=asset_name,
                    chain_code="",
                    chain_name="",
                    AD=False, AW=False,
                    conf_dep=0, conf_wd=0,
                    dep_min=D(0), dep_max=D(0),
                    wd_min=D(0), wd_max=D(0),
                    dep_fee_pct=D(0), dep_fee_fix=D(0),
                    wd_fee_pct=D(0), wd_fee_fix=D(0),
                    requires_memo=False,
                    amount_precision=amount_precision_root,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    raw_meta={"asset": json_safe(item)},
                )
                continue

            for ch in chains:
                chain_code = U(ch.get("chainId") or ch.get("chainName")) or "NATIVE"
                chain_name = disp(ch.get("chainName")) or chain_code

                api_dep = B(ch.get("isDepositEnabled"))
                api_wd  = B(ch.get("isWithdrawEnabled"))

                dep_conf = int(ch.get("preConfirms") or 0)
                wd_conf  = int(ch.get("confirms") or dep_conf)

                dep_min = D(ch.get("depositMinSize") or 0)
                dep_max = D(ch.get("maxDeposit") or 0)
                wd_min  = D(ch.get("withdrawalMinSize") or 0)
                wd_max  = D(ch.get("maxWithdraw") or 0)

                wd_fee_fix = D(ch.get("withdrawalMinFee") or 0)
                wd_fee_pct = D(ch.get("withdrawFeeRate") or 0)  # трактуем «как есть»
                dep_fee_fix = D(0)
                dep_fee_pct = D(0)

                amount_precision = int(ch.get("withdrawPrecision") or amount_precision_root)
                requires_memo = B(ch.get("needTag")) or (chain_code in memo_chains) or (U(chain_name) in memo_chains)

                yield ProviderRow(
                    asset_code=sym,
                    asset_name=asset_name,
                    chain_code=chain_code,
                    chain_name=chain_name,
                    AD=api_dep,
                    AW=api_wd,
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
                    requires_memo=requires_memo,
                    amount_precision=amount_precision,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    raw_meta={"asset": json_safe(item)},
                )
