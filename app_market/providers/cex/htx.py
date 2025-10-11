from __future__ import annotations

from typing import Iterable, List
import requests

from app_market.providers.base import UnifiedProviderBase, ProviderRow
from app_market.providers.http import SESSION
from app_market.providers.numeric import (
    D, U, B, disp, json_safe,
    stable_set, memo_required_set,
)

HTX_BASES: List[str] = ["https://api.htx.com", "https://api.huobi.pro", "https://api.huobi.com"]
CURRENCIES_PATH = "/v2/reference/currencies"


class HtxAdapter(UnifiedProviderBase):
    code = "HTX"

    def fetch_payload(self, *, timeout: int) -> list[dict]:
        last_exc: Exception | None = None
        for base in HTX_BASES:
            try:
                resp = SESSION.get(base + CURRENCIES_PATH, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and data.get("data"):
                    return list(data.get("data") or [])
            except Exception as e:
                last_exc = e
                continue
        if last_exc:
            raise last_exc
        return []

    def iter_rows(self, payload: list[dict]) -> Iterable[ProviderRow]:
        stables = stable_set()
        memo_chains = memo_required_set()

        for item in payload:
            sym = U(item.get("currency"))
            if not sym:
                continue
            asset_name = disp(item.get("currency")) or sym
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
                    amount_precision=8,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    raw_meta={"asset": json_safe(item)},
                )
                continue

            for ch in chains:
                chain_code = U(ch.get("chain")) or U(ch.get("baseChain")) or "NATIVE"
                chain_name = disp(ch.get("displayName")) or chain_code

                api_dep = B(ch.get("depositStatus"))
                api_wd = B(ch.get("withdrawStatus"))

                dep_conf = int(ch.get("numOfFastConfirmations") or 0)
                wd_conf = int(ch.get("numOfConfirmations") or dep_conf)

                dep_min = D(ch.get("minDepositAmt") or 0)
                dep_max = D(0)
                wd_min = D(ch.get("minWithdrawAmt") or 0)
                wd_max = D(ch.get("maxWithdrawAmt") or 0)

                wd_fee_fix = D(0)
                wd_fee_pct = D(0)
                dep_fee_fix = D(0)
                dep_fee_pct = D(0)

                wft = ch.get("withdrawFeeType")
                if wft in ("circulated", "ratio"):
                    wd_fee_fix = D(ch.get("minTransactFeeWithdraw") or 0)
                else:
                    wd_fee_fix = D(ch.get("transactFeeWithdraw") or 0)

                requires_memo = B(ch.get("addrDepositTag")) or (chain_code in memo_chains) or (U(chain_name) in memo_chains)
                amount_precision = int(ch.get("withdrawPrecision") or 8)

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
