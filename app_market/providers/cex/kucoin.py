from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any, Iterable
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from app_market.models.exchange import Exchange
from app_market.providers.base import UnifiedProviderBase, ProviderRow
from app_market.providers.numeric import (
    UA, D, U, B, disp, json_safe,
    stable_set, memo_required_set,
)

KU_BASE = "https://api.kucoin.com"
CURRENCY_URL = f"{KU_BASE}/api/v3/currencies"


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


class KucoinAdapter(UnifiedProviderBase):
    code = "KUCOIN"

    def provider_name_for_status(self) -> str:
        return "KuCoin"

    # --- тонкая часть: запрос и маппинг в ProviderRow ---

    def fetch_payload(self, *, timeout: int) -> list[dict]:
        data = _http_get_json(CURRENCY_URL, timeout=timeout, retries=3)
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
            amount_precision = int(item.get("precision") or 8)

            chains = item.get("chains") or []
            if not isinstance(chains, list) or len(chains) == 0:
                # без сетей — базовый конвейер сам решит FIAT/NOTDEFINED и выставит AD/AW
                yield ProviderRow(
                    asset_code=sym,
                    asset_name=asset_name,
                    chain_code="",  # важно: пусто => «без сетей»
                    chain_name="",
                    AD=False, AW=False,  # для безсетевых перезапишется в базе
                    conf_dep=0, conf_wd=0,
                    dep_min=D(0), dep_max=D(0),
                    wd_min=D(0), wd_max=D(0),
                    dep_fee_pct=D(0), dep_fee_fix=D(0),
                    wd_fee_pct=D(0), wd_fee_fix=D(0),
                    requires_memo=False,
                    amount_precision=amount_precision,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    raw_meta={"asset": json_safe(item)},  # только корневой объект
                )
                continue

            for ch in chains:
                chain_code = U(ch.get("chainId") or ch.get("chainName")) or "NATIVE"
                chain_name = disp(ch.get("chainName")) or chain_code

                # «как заявлено API» (до учёта подтверждений)
                api_dep = B(ch.get("isDepositEnabled"))
                api_wd = B(ch.get("isWithdrawEnabled"))

                # подтверждения: депозит и вывод (если для вывода нет — берём депозитные)
                dep_conf = int(ch.get("preConfirms") or 0)
                wd_conf = int(ch.get("confirms") or dep_conf)

                # лимиты/комиссии
                dep_min = D(ch.get("depositMinSize") or 0)
                dep_max = D(ch.get("maxDeposit") or 0)

                wd_min = D(ch.get("withdrawalMinSize") or 0)
                wd_max = D(ch.get("maxWithdraw") or 0)

                wd_fee_fix = D(ch.get("withdrawalMinFee") or 0)
                if ch.get("withdrawFeeRate") in ["0.01", "0.004", "0.002", "0.001"]:
                    pass
                wd_fee_pct = D(ch.get("withdrawFeeRate") or 0)
                dep_fee_fix = D(0)
                dep_fee_pct = D(0)

                amount_precision = D(ch.get("withdrawPrecision") or 8)
                requires_memo = B(ch.get("needTag")) or (chain_code in memo_chains) or (U(chain_name) in memo_chains)

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
                    raw_meta={"asset": json_safe(item)},  # только корневой объект
                )
