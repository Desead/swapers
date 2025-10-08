from __future__ import annotations

import json
import time
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
    UA, D, to_db_amount, to_db_percent, json_safe,
    U, disp, B,
    stable_set, memo_required_set,
    ensure_wd_conf_ge_dep, infer_asset_kind,
    crypto_withdraw_guard,
)

KU_BASE = "https://api.kucoin.com"
CURRENCY_URL = f"{KU_BASE}/api/v3/currencies"


# ---------- helpers ----------

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

class KucoinAdapter(ProviderAdapter):
    code = "KUCOIN"

    def _fetch_public(self, *, timeout: int) -> list[dict]:
        data = _http_get_json(CURRENCY_URL, timeout=timeout, retries=3)
        if not isinstance(data, dict) or data.get("code") != "200000":
            return []
        return list(data.get("data") or [])

    def _rows_from_public(self, payload: list[dict]) -> list[_Row]:
        stables = stable_set()
        memo_chains = memo_required_set()
        rows: list[_Row] = []

        for item in payload:
            sym = U(item.get("currency"))
            if not sym:
                continue
            asset_name = disp(item.get("fullName")) or sym

            chains = item.get("chains") or []
            # Редкий кейс без chains — трактуем как FIAT-заглушку
            if not chains:
                rows.append(_Row(
                    asset_code=sym, asset_name=asset_name,
                    chain_code="FIAT", chain_name="FIAT",
                    AD=False, AW=False,
                    conf_dep=0, conf_wd=0,
                    dep_min=D(0), dep_max=D(0),
                    wd_min=D(0), wd_max=D(0),
                    dep_fee_pct=D(0), dep_fee_fix=D(0),
                    wd_fee_pct=D(0), wd_fee_fix=D(0),
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    requires_memo=False,
                    amount_precision=int(item.get("precision") or 8),
                    raw_meta=json_safe(item),
                ))
                continue

            for ch in chains:
                chain_code = U(ch.get("chainName") or ch.get("chain")) or "NATIVE"
                chain_disp = disp(ch.get("chainName")) or chain_code

                # Включённость депозита/вывода: новая и старая схемы
                can_dep = B(ch.get("isDepositEnabled"), ch.get("enableDeposit"))
                can_wd  = B(ch.get("isWithdrawEnabled"), ch.get("enableWithdraw"))

                # Подтверждения
                dep_conf = int(ch.get("confirms") or 0)
                wd_conf  = int(ch.get("safeConfirms") or dep_conf)
                dep_conf, wd_conf = ensure_wd_conf_ge_dep(dep_conf, wd_conf)

                # Лимиты и комиссии: поддерживаем разные вариации ключей
                dep_min = D(ch.get("depositMinSize") or ch.get("depositMin") or 0)
                dep_max = D(0)

                wd_min = D(ch.get("withdrawalMinSize") or ch.get("withdrawMinSize") or ch.get("withdrawMin") or 0)
                wd_max = D(ch.get("withdrawalMaxSize") or ch.get("withdrawMaxSize") or ch.get("withdrawMax") or 0)

                wd_fee_fix = D(ch.get("withdrawalMinFee") or ch.get("withdrawMinFee") or ch.get("withdrawalFee") or ch.get("withdrawFee") or 0)
                wd_fee_pct = D(0)
                dep_fee_fix = D(0)
                dep_fee_pct = D(0)

                requires_memo = B(ch.get("needTag")) or (chain_code in memo_chains) or (U(chain_disp) in memo_chains)
                amount_precision = int(item.get("precision") or 8)

                rows.append(_Row(
                    asset_code=sym, asset_name=asset_name,
                    chain_code=chain_code, chain_name=chain_disp,
                    AD=can_dep, AW=can_wd,
                    conf_dep=dep_conf, conf_wd=wd_conf,
                    dep_min=dep_min, dep_max=dep_max,
                    wd_min=wd_min, wd_max=wd_max,
                    dep_fee_pct=dep_fee_pct, dep_fee_fix=dep_fee_fix,
                    wd_fee_pct=wd_fee_pct, wd_fee_fix=wd_fee_fix,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    requires_memo=requires_memo,
                    amount_precision=amount_precision,
                    raw_meta=json_safe({"asset": item, "chain": ch}),
                ))
        return rows

    @transaction.atomic
    def sync_assets(self, exchange: Exchange, *, timeout: int = 20, limit: int = 0, reconcile: bool = True, verbose: bool = False) -> AssetSyncStats:
        stats = AssetSyncStats()
        change_counter = Counter()

        try:
            payload = self._fetch_public(timeout=timeout)
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            raise RuntimeError(f"KuCoin: ошибка запросов: {e}")

        rows = self._rows_from_public(payload)
        if limit and limit > 0:
            rows = rows[:limit]

        seen: Set[Tuple[str, str]] = set()
        for r in rows:
            stats.processed += 1

            # Определяем вид актива (FIAT/CRYPTO) единообразно
            kind = infer_asset_kind(r.asset_code, r.chain_code, r.chain_name)
            prec = int(r.amount_precision or 8)

            # Централизованные лимиты — применяем только к крипто-цепям
            if kind == AssetKind.CRYPTO:
                ok, wd_min_q, wd_fee_fix_q = crypto_withdraw_guard(r.wd_min, r.wd_fee_fix, prec)
                if not ok:
                    stats.skipped += 1
                    continue
            else:
                wd_min_q = to_db_amount(r.wd_min, prec)
                wd_fee_fix_q = to_db_amount(r.wd_fee_fix, prec)

            # прошла валидации — учитываем как присутствующую
            seen.add((r.asset_code, r.chain_code))

            # Корректируем подтверждения: для CRYPTO гарантируем минимум 1 на депозит
            dep_conf = r.conf_dep
            wd_conf = r.conf_wd
            if kind == AssetKind.CRYPTO and dep_conf < 1:
                dep_conf = 1
                wd_conf = max(wd_conf, dep_conf)

            new_vals = dict(
                asset_name=r.asset_name,
                AD=bool(r.AD),
                AW=bool(r.AW),
                confirmations_deposit=int(dep_conf),
                confirmations_withdraw=int(wd_conf),

                deposit_fee_percent=to_db_percent(r.dep_fee_pct),
                deposit_fee_fixed=to_db_amount(r.dep_fee_fix, prec),
                deposit_min=to_db_amount(r.dep_min, prec),
                deposit_max=to_db_amount(r.dep_max, prec),
                # deposit_min_usdt — не трогаем
                # deposit_max_usdt — не трогаем

                withdraw_fee_percent=to_db_percent(r.wd_fee_pct),
                withdraw_fee_fixed=wd_fee_fix_q,
                withdraw_min=wd_min_q,
                withdraw_max=to_db_amount(r.wd_max, prec),
                # withdraw_min_usdt — не трогаем
                # withdraw_max_usdt — не трогаем

                requires_memo=bool(r.requires_memo),
                is_stablecoin=bool(r.is_stable),
                amount_precision=prec,
                asset_kind=kind,
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
                    AD=False, AW=False, status_note="Отключено: отсутствует в выдаче KuCoin", updated_at=timezone.now()
                )
                stats.disabled = len(to_disable)

        if verbose:
            print(f"[KuCoin] processed={stats.processed} created={stats.created} updated={stats.updated} skipped={stats.skipped} disabled={stats.disabled}")
            if change_counter:
                top = ", ".join(f"{k}={v}" for k, v in change_counter.most_common(10))
                print(f"[KUCOIN] field changes breakdown: {top}")
        return stats
