from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, localcontext
from typing import Any, Optional, Set, Tuple, Dict
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from collections import Counter

from django.db import transaction
from django.utils import timezone

from app_market.models.exchange import Exchange
from app_market.models.exchange_asset import ExchangeAsset, AssetKind
from app_main.models import SiteSetup
from .base import ProviderAdapter, AssetSyncStats

UA = "swapers-sync/1.0 (+https://github.com/Desead/swapers)"
HTX_BASES = ["https://api.htx.com", "https://api.huobi.pro", "https://api.huobi.com"]
CURRENCIES_PATH = "/v2/reference/currencies"

# precision config
PCT_MAX_DIGITS, PCT_PLACES = 12, 5
AMOUNT_MAX_DIGITS, AMOUNT_PLACES = 20, 8

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

def _D(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        d = x
    else:
        if x in (None, "", "0E-10"):
            return Decimal("0")
        s = str(x).strip()
        if s.lower() in {"nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
            return Decimal("0")
        try:
            d = Decimal(s)
        except (InvalidOperation, ValueError, TypeError):
            return Decimal("0")
    return d if d.is_finite() else Decimal("0")

def _cap_and_quantize(d: Decimal, *, max_digits: int, places: int) -> Decimal:
    if not d.is_finite():
        return Decimal("0")
    if d == 0:
        return Decimal("0").quantize(Decimal(1).scaleb(-places))
    exp = Decimal(1).scaleb(-places)
    max_int = max_digits - places
    limit = (Decimal(10) ** max_int) - exp
    if d > limit:
        d = limit
    elif d < -limit:
        d = -limit
    with localcontext() as ctx:
        ctx.rounding = ROUND_DOWN
        try:
            return d.quantize(exp)
        except InvalidOperation:
            return Decimal("0").quantize(exp)

def _q_pct(x: Any) -> Decimal:
    return _cap_and_quantize(_D(x), max_digits=PCT_MAX_DIGITS, places=PCT_PLACES)

def _q_amt(x: Any) -> Decimal:
    return _cap_and_quantize(_D(x), max_digits=AMOUNT_MAX_DIGITS, places=AMOUNT_PLACES)

def _B(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    if isinstance(x, str):
        v = x.strip().lower()
        return v in {"1", "true", "yes", "y", "on", "enabled", "allow", "allowed"}
    return False

def _U(s: Optional[str]) -> str:
    return (s or "").strip().upper()

def _disp(s: Optional[str]) -> str:
    return (s or "").strip()

def _json_safe(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return o

def _stable_set_from_sitesetup() -> Set[str]:
    ss = SiteSetup.get_solo()
    raw = ss.stablecoins or ""
    parts = [p.strip() for p in str(raw).replace(";", ",").split(",") if p.strip()]
    return {p.upper() for p in parts}

def _memo_required_chains_from_site() -> Set[str]:
    ss = SiteSetup.get_solo()
    try:
        return set(ss.get_memo_required_chains_set())  # type: ignore[attr-defined]
    except Exception:
        txt = (getattr(ss, "memo_required_chains", "") or "").strip()
        if not txt:
            return set()
        return {p.strip().upper() for p in txt.replace(";", ",").split(",") if p.strip()}

def _ensure_wd_conf_ge_dep(dep_conf: int, wd_conf: int) -> tuple[int, int]:
    if wd_conf < dep_conf:
        wd_conf = dep_conf
    return dep_conf, wd_conf

@dataclass
class _Row:
    asset_code: str
    asset_name: str
    chain_code: str
    chain_display: str
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

class HtxAdapter(ProviderAdapter):
    code = "HTX"

    def _fetch_public(self, *, timeout: int) -> list[dict]:
        last_err: Optional[Exception] = None
        for base in HTX_BASES:
            try:
                data = _http_get_json(base + CURRENCIES_PATH, timeout=timeout, retries=3)
                if isinstance(data, dict) and data.get("data"):
                    return list(data.get("data") or [])
            except (URLError, HTTPError, json.JSONDecodeError) as e:
                last_err = e
                continue
        if last_err:
            raise last_err
        return []

    def _rows_from_public(self, payload: list[dict]) -> list[_Row]:
        stables = _stable_set_from_sitesetup()
        memo_chains = _memo_required_chains_from_site()
        rows: list[_Row] = []

        for item in payload:
            sym = _U(item.get("currency"))
            if not sym:
                continue
            asset_name = _disp(item.get("currency")) or sym
            chains = item.get("chains") or []
            if not isinstance(chains, list):
                continue

            for ch in chains:
                chain_code = _U(ch.get("chain")) or _U(ch.get("baseChain")) or "NATIVE"
                chain_display = _disp(ch.get("displayName")) or chain_code

                can_dep = _B(ch.get("depositEnable") or ch.get("depositStatus"))
                can_wd = _B(ch.get("withdrawEnable") or ch.get("withdrawStatus"))

                dep_conf = int(ch.get("numOfConfirmations") or 0)
                wd_conf = int(ch.get("numOfFastConfirmations") or dep_conf)
                dep_conf, wd_conf = _ensure_wd_conf_ge_dep(dep_conf, wd_conf)
                if dep_conf < 1:
                    dep_conf = 1
                    wd_conf = max(wd_conf, dep_conf)

                dep_min = _D(ch.get("depositMinAmount") or ch.get("minDepositAmt") or 0)
                dep_max = _D(ch.get("depositMaxAmount") or ch.get("maxDepositAmt") or 0)
                wd_min = _D(ch.get("withdrawMinAmount") or ch.get("minWithdrawAmt") or 0)
                wd_max = _D(ch.get("withdrawMaxAmount") or ch.get("maxWithdrawAmt") or 0)

                wd_fee_fix = _D(ch.get("transactFeeWithdraw") or ch.get("txFee") or 0)
                wd_fee_pct = _D(0)
                dep_fee_fix = _D(0)
                dep_fee_pct = _D(0)

                desc = " ".join([
                    _disp(ch.get("depositDesc")), _disp(ch.get("withdrawDesc")), _disp(ch.get("tips")),
                ]).lower()
                requires_memo = ("memo" in desc) or ("tag" in desc) or (chain_code in memo_chains) or (_U(chain_display) in memo_chains)

                amount_precision = int(ch.get("withdrawPrecision") or ch.get("txTransferPrecision") or 8)

                rows.append(_Row(
                    asset_code=sym, asset_name=asset_name,
                    chain_code=chain_code, chain_display=chain_display,
                    AD=can_dep, AW=can_wd,
                    conf_dep=dep_conf, conf_wd=wd_conf,
                    dep_min=dep_min, dep_max=dep_max,
                    wd_min=wd_min, wd_max=wd_max,
                    dep_fee_pct=dep_fee_pct, dep_fee_fix=dep_fee_fix,
                    wd_fee_pct=wd_fee_pct, wd_fee_fix=wd_fee_fix,
                    is_stable=(sym in stables) or (_U(asset_name) in stables),
                    requires_memo=requires_memo,
                    amount_precision=amount_precision,
                    raw_meta=_json_safe({"asset": item, "chain": ch}),
                ))
        return rows

    @transaction.atomic
    def sync_assets(self, exchange: Exchange, *, timeout: int = 20, limit: int = 0, reconcile: bool = True, verbose: bool = False) -> AssetSyncStats:
        stats = AssetSyncStats()
        change_counter = Counter()

        try:
            payload = self._fetch_public(timeout=timeout)
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            raise RuntimeError(f"HTX: ошибка запросов: {e}")

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
                confirmations_deposit=int(r.conf_dep if r.conf_dep > 0 else 1),
                confirmations_withdraw=int(max(r.conf_dep if r.conf_dep > 0 else 1, r.conf_wd)),
                deposit_fee_percent=_q_pct(r.dep_fee_pct),
                deposit_fee_fixed=_q_amt(r.dep_fee_fix),
                deposit_min=_q_amt(r.dep_min),
                deposit_max=_q_amt(r.dep_max),
                deposit_min_usdt=_q_amt(0),
                deposit_max_usdt=_q_amt(0),
                withdraw_fee_percent=_q_pct(r.wd_fee_pct),
                withdraw_fee_fixed=_q_amt(r.wd_fee_fix),
                withdraw_min=_q_amt(r.wd_min),
                withdraw_max=_q_amt(r.wd_max),
                withdraw_min_usdt=_q_amt(0),
                withdraw_max_usdt=_q_amt(0),
                requires_memo=bool(r.requires_memo),
                is_stablecoin=bool(r.is_stable),
                amount_precision=int(r.amount_precision or 8),
                asset_kind=AssetKind.CRYPTO,
                provider_symbol=r.asset_code,
                provider_chain=r.chain_code,
            )
            obj, created = ExchangeAsset.objects.get_or_create(
                exchange=exchange, asset_code=r.asset_code, chain_code=r.chain_code,
                defaults={**new_vals, "raw_metadata": _json_safe(r.raw_meta), "chain_display": r.chain_display, "asset_name": r.asset_name},
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
                    obj.raw_metadata = _json_safe(r.raw_meta)
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
                    AD=False, AW=False, status_note="Отключено: отсутствует в выдаче HTX", updated_at=timezone.now()
                )
                stats.disabled = len(to_disable)

        if verbose:
            print(f"[HTX] processed={stats.processed} created={stats.created} updated={stats.updated} skipped={stats.skipped} disabled={stats.disabled}")
            if change_counter:
                top = ", ".join(f"{k}={v}" for k, v in change_counter.most_common(10))
                print(f"[HTX] field changes breakdown: {top}")
        return stats
