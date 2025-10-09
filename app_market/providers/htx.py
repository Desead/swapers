from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List
from unittest import case
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from app_market.models.exchange import Exchange
from .base import UnifiedProviderBase, ProviderRow
from .numeric import (
    UA, D, U, B, disp, json_safe,
    stable_set, memo_required_set,
)

HTX_BASES = ["https://api.htx.com", "https://api.huobi.pro", "https://api.huobi.com"]
CURRENCIES_PATH = "/v2/reference/currencies"


def _http_get_json(url: str, timeout: int = 20, retries: int = 3) -> Any:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(0.3 * (3 ** attempt))
    assert last_err is not None
    raise last_err


class HtxAdapter(UnifiedProviderBase):
    code = "HTX"

    # --- тонкая часть: запрос и маппинг в ProviderRow ---

    def fetch_payload(self, *, timeout: int) -> list[dict]:
        last_err: Exception | None = None
        for base in HTX_BASES:
            try:
                data = _http_get_json(base + CURRENCIES_PATH, timeout=timeout, retries=3)
                if isinstance(data, dict) and data.get("data"):
                    return list(data.get("data") or [])
            except (URLError, HTTPError, json.JSONDecodeError) as e:
                last_err = e
        if last_err:
            raise RuntimeError(f"HTX: ошибка запросов: {last_err}")
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
                # без сетей: база сама решит FIAT/NOTDEFINED и выставит AD/AW
                yield ProviderRow(
                    asset_code=sym,
                    asset_name=asset_name,
                    chain_code="",  # важно: пусто => «без сетей»
                    chain_name="",
                    AD=False, AW=False,  # неважно для безсетевых — база перезапишет
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

                # «как заявлено API» (до учёта подтверждений)
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

                match ch.get("withdrawFeeType"):
                    case 'circulated', 'ratio':
                        wd_fee_fix = D(ch.get("minTransactFeeWithdraw") or 0)
                    case _:
                        wd_fee_fix = D(ch.get("transactFeeWithdraw") or 0)

                requires_memo = B(ch.get("addrDepositTag")) or (chain_code in memo_chains) or (U(chain_name) in memo_chains)
                amount_precision = int(ch.get("withdrawPrecision") or 8)

                yield ProviderRow(
                    asset_code=sym,
                    asset_name=asset_name,
                    chain_code=chain_code,  # наличие сети => база классифицирует как CRYPTO
                    chain_name=chain_name,
                    AD=bool(api_dep),
                    AW=bool(api_wd),
                    conf_dep=int(dep_conf),
                    conf_wd=int(wd_conf),
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
                    raw_meta={"asset": json_safe(item)},
                )
