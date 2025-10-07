from __future__ import annotations

import json
import time
import hmac
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Set, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from collections import Counter

from django.db import transaction
from django.utils import timezone

from app_market.models.exchange import Exchange
from app_market.models.exchange_asset import ExchangeAsset, AssetKind
from .base import ProviderAdapter, AssetSyncStats
from .numeric import (
    UA, D, q_amount, q_percent, json_safe,
    U, disp, B,
    stable_set, memo_required_set,
    ensure_wd_conf_ge_dep, get_any_enabled_keys,
)

BYBIT_BASE = "https://api.bybit.com"
COIN_INFO_URL = f"{BYBIT_BASE}/v5/asset/coin/query-info"
RECV_WINDOW = "5000"

# ---------- helpers ----------

def _http_get_json(url: str, headers: Dict[str, str] | None = None, timeout: int = 20, retries: int = 3) -> Any:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers=(headers or {"User-Agent": UA}))
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(0.3 * (3 ** attempt))
    assert last_err is not None
    raise last_err


def _bybit_pct_to_percent(v: Any) -> Decimal:
    # у Bybit это доля (0.001) -> проценты (0.1)
    return D(v) * Decimal("100")


# ---------- row ----------

@dataclass
class _Row:
    asset_code: str
    asset_name: str
    chain_code: str
    chain_name: str
    AD: bool
    AW: bool
    conf_dep: int
    conf_wd: int
    dep_min: Decimal
    dep_max: Decimal
    wd_min: Decimal
    wd_max: Decimal
    dep_fee_pct: Decimal
    dep_fee_fix: Decimal
    wd_fee_pct: Decimal
    wd_fee_fix: Decimal
    is_stable: bool
    requires_memo: bool
    amount_precision: int
    raw_meta: dict


# ---------- adapter ----------

class BybitAdapter(ProviderAdapter):
    code = "BYBIT"

    def _fetch_coin_info_signed(self, *, api_key: str, api_secret: str, timeout: int) -> list[dict]:
        ts = str(int(time.time() * 1000))
        query = ""
        prehash = ts + api_key + RECV_WINDOW + query
        sign = hmac.new(api_secret.encode(), prehash.encode(), hashlib.sha256).hexdigest()
        headers = {
            "User-Agent": UA,
            "Accept": "application/json",
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
            "X-BAPI-SIGN": sign,
            "X-BAPI-SIGN-TYPE": "2",
        }
        data = _http_get_json(COIN_INFO_URL, headers=headers, timeout=timeout, retries=3)
        if not isinstance(data, dict):
            return []
        if int(data.get("retCode", -1)) != 0:
            raise RuntimeError(f"Bybit API error: retCode={data.get('retCode')} retMsg={data.get('retMsg')}")
        result = data.get("result") or {}
        rows = result.get("rows") or []
        return list(rows) if isinstance(rows, list) else []

    def _rows_from_public(self, payload: list[dict]) -> list[_Row]:
        stables = stable_set()
        memo_chains = memo_required_set()
        rows: list[_Row] = []

        for item in payload:
            sym = U(item.get("coin"))
            if not sym:
                continue
            asset_name = disp(item.get("name")) or sym
            remain_amount = D(item.get("remainAmount"))
            chains = item.get("chains") or []

            # FIAT кейс
            if not chains:
                rows.append(_Row(
                    asset_code=sym, asset_name=asset_name,
                    chain_code="FIAT", chain_name="FIAT",
                    AD=False, AW=False,
                    conf_dep=0, conf_wd=0,
                    dep_min=D(0), dep_max=D(0),
                    wd_min=D(0), wd_max=remain_amount if remain_amount > 0 else D(0),
                    dep_fee_pct=D(0), dep_fee_fix=D(0),
                    wd_fee_pct=D(0), wd_fee_fix=D(0),
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    requires_memo=False,
                    amount_precision=8,
                    raw_meta=json_safe(item),
                ))
                continue

            for ch in chains:
                chain_code = U(ch.get("chain")) or "NATIVE"
                chain_disp = disp(ch.get("chainType")) or chain_code
                can_dep = B(ch.get("chainDeposit"))
                can_wd = B(ch.get("chainWithdraw"))

                dep_conf = int(ch.get("confirmation") or 0)
                safe_conf = int(ch.get("safeConfirmNumber") or 0)
                dep_conf, wd_conf = ensure_wd_conf_ge_dep(dep_conf, safe_conf)
                if dep_conf < 1:
                    dep_conf = 1
                    wd_conf = max(wd_conf, dep_conf)

                dep_min = D(ch.get("depositMin") or 0); dep_max = D(0)
                wd_min = D(ch.get("withdrawMin") or 0)
                wd_max = remain_amount if remain_amount > 0 else D(0)

                wd_fee_fix = D(ch.get("withdrawFee") or 0)
                wd_fee_pct = _bybit_pct_to_percent(ch.get("withdrawPercentageFee") or 0)

                requires_memo = (chain_code in memo_chains) or (U(chain_disp) in memo_chains)
                amount_precision = int(ch.get("minAccuracy") or 8)

                rows.append(_Row(
                    asset_code=sym, asset_name=asset_name,
                    chain_code=chain_code, chain_name=chain_disp,
                    AD=can_dep, AW=can_wd,
                    conf_dep=dep_conf, conf_wd=wd_conf,
                    dep_min=dep_min, dep_max=D(0),
                    wd_min=wd_min, wd_max=wd_max,
                    dep_fee_pct=D(0), dep_fee_fix=D(0),
                    wd_fee_pct=wd_fee_pct, wd_fee_fix=wd_fee_fix,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    requires_memo=requires_memo,
                    amount_precision=amount_precision,
                    raw_meta=json_safe({"coin": item, "chain": ch}),
                ))
        return rows

    @transaction.atomic
    def sync_assets(self, exchange: Exchange, *, timeout: int = 20, limit: int = 0, reconcile: bool = True, verbose: bool = False) -> AssetSyncStats:
        stats = AssetSyncStats()
        change_counter = Counter()

        api_key, api_secret = get_any_enabled_keys(exchange)
        if not api_key or not api_secret:
            raise RuntimeError("Нет активных API-ключей Bybit для этого провайдера")

        try:
            payload = self._fetch_coin_info_signed(api_key=api_key, api_secret=api_secret, timeout=timeout)
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Bybit: ошибка запросов: {e}")

        rows = self._rows_from_public(payload)
        if limit and limit > 0:
            rows = rows[:limit]

        seen: Set[Tuple[str, str]] = set()
        for r in rows:
            stats.processed += 1
            seen.add((r.asset_code, r.chain_code))

            new_vals = dict(
                asset_name=r.asset_name,
                AD=bool(r.AD),
                AW=bool(r.AW),
                confirmations_deposit=int(r.conf_dep if r.conf_dep > 0 or r.chain_code == "FIAT" else 1),
                confirmations_withdraw=int(max(r.conf_dep if r.conf_dep > 0 else 1, r.conf_wd)),
                deposit_fee_percent=q_percent(r.dep_fee_pct),
                deposit_fee_fixed=q_amount(r.dep_fee_fix, r.amount_precision),
                deposit_min=q_amount(r.dep_min, r.amount_precision),
                deposit_max=q_amount(r.dep_max, r.amount_precision),
                # deposit_min_usdt=q_amount(D(0), r.amount_precision),
                # deposit_max_usdt=q_amount(D(0), r.amount_precision),
                withdraw_fee_percent=q_percent(r.wd_fee_pct),
                withdraw_fee_fixed=q_amount(r.wd_fee_fix, r.amount_precision),
                withdraw_min=q_amount(r.wd_min, r.amount_precision),
                withdraw_max=q_amount(r.wd_max, r.amount_precision),
                # withdraw_min_usdt=q_amount(D(0), r.amount_precision),
                # withdraw_max_usdt=q_amount(D(0), r.amount_precision),
                requires_memo=bool(r.requires_memo),
                is_stablecoin=bool(r.is_stable),
                amount_precision=int(r.amount_precision or 8),
                asset_kind=AssetKind.CRYPTO if r.chain_code != "FIAT" else AssetKind.FIAT,
                provider_symbol=r.asset_code,
                provider_chain=r.chain_code,
            )
            obj, created = ExchangeAsset.objects.get_or_create(
                exchange=exchange, asset_code=r.asset_code, chain_code=r.chain_code,
                defaults={**new_vals, "raw_metadata": json_safe(r.raw_meta), "chain_name": r.chain_name, "asset_name": r.asset_name},
            )
            if created:
                stats.created += 1
            else:
                changed: list[str] = []
                for f, v in new_vals.items():
                    if getattr(obj, f) != v:
                        setattr(obj, f, v)
                        changed.append(f)
                if changed:
                    for f in changed:
                        change_counter[f] += 1
                    obj.raw_metadata = json_safe(r.raw_meta)
                    obj.save(update_fields=changed + ["raw_metadata", "updated_at"])
                    stats.updated += 1
                else:
                    stats.skipped += 1

        if reconcile:
            to_disable = []
            for obj in ExchangeAsset.objects.filter(exchange=exchange).only("id", "asset_code", "chain_code", "AD", "AW"):
                key = (obj.asset_code, obj.chain_code)
                if key not in seen and (obj.AD or obj.AW):
                    to_disable.append(obj.id)
            if to_disable:
                ExchangeAsset.objects.filter(id__in=to_disable).update(
                    AD=False, AW=False, status_note="Отключено: отсутствует в выдаче Bybit", updated_at=timezone.now()
                )
                stats.disabled = len(to_disable)

        if verbose:
            print(f"[Bybit] processed={stats.processed} created={stats.created} updated={stats.updated} skipped={stats.skipped} disabled={stats.disabled}")
            if change_counter:
                top = ", ".join(f"{k}={v}" for k, v in change_counter.most_common(10))
                print(f"[BYBIT] field changes breakdown: {top}")
        return stats
