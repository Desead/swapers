# app_market/providers/mexc.py
from __future__ import annotations

import hmac
import hashlib
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Set, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from django.db import transaction
from django.utils import timezone

from app_market.models.exchange import Exchange
from app_market.models.exchange_asset import ExchangeAsset, AssetKind
from .base import ProviderAdapter, AssetSyncStats
from .numeric import (
    UA, D, q_amount, q_percent, json_safe,
    U, disp, B,
    stable_set, memo_required_set,
    infer_asset_kind, get_any_enabled_keys,
)

BASE = "https://api.mexc.com"
CAPITAL_CONFIG_URL = "/api/v3/capital/config/getall"


def _mexc_sign(secret: str, query: str) -> str:
    return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()


def _http_get_json_signed(path: str, api_key: str, api_secret: str, *, timeout: int = 20, retries: int = 2) -> Any:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            ts = int(time.time() * 1000)
            qs = urlencode({"timestamp": ts, "recvWindow": 20000})
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
    asset_kind: str
    raw_meta: dict


class MexcAdapter(ProviderAdapter):
    code = "MEXC"

    def _rows_from_payload(self, payload: Any) -> list[_Row]:
        stables = stable_set()
        memo_chains = memo_required_set()
        out: list[_Row] = []

        if not isinstance(payload, list):
            return out

        for coin in payload:
            sym = U(coin.get("coin") or coin.get("asset"))
            if not sym:
                continue
            asset_name = disp(coin.get("name") or coin.get("fullName") or sym)

            networks = coin.get("networkList") or coin.get("chains") or []
            if not isinstance(networks, list) or not networks:
                out.append(_Row(
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
                    amount_precision=8,
                    asset_kind=AssetKind.FIAT,
                    raw_meta=json_safe(coin),
                ))
                continue

            for net in networks:
                chain_code = U(net.get("network") or net.get("chain") or net.get("name"))
                if not chain_code:
                    continue
                chain_name = disp(net.get("name") or net.get("network") or chain_code)

                can_dep = B(net.get("depositEnable"), net.get("canDeposit"))
                can_wd = B(net.get("withdrawEnable"), net.get("canWithdraw"))

                dep_conf = int(D(net.get("minConfirm") or net.get("confirmTimes") or 0))
                if dep_conf < 0:
                    dep_conf = 0
                wd_conf = dep_conf

                dep_min = D(net.get("depositMin"))
                dep_max = D(net.get("depositMax"))
                wd_min = D(net.get("withdrawMin"))
                wd_max = D(net.get("withdrawMax"))

                wd_fee_fix = D(net.get("withdrawFee"))
                wd_fee_pct = D(net.get("withdrawFeePercent") or 0)
                dep_fee_fix = D(net.get("depositFee") or net.get("depositFeeFixed") or 0)
                dep_fee_pct = D(net.get("depositFeePercent") or 0)

                requires_memo = B(net.get("needTag"))
                if not requires_memo:
                    tips = (disp(net.get("specialTips") or "")).lower()
                    if "memo" in tips or "tag" in tips:
                        requires_memo = True
                if not requires_memo and (chain_code in memo_chains or U(chain_name) in memo_chains):
                    requires_memo = True

                amount_precision = int(D(net.get("withdrawPrecision") or net.get("accuracy") or 8))
                if amount_precision < 0:
                    amount_precision = 0
                if amount_precision > 18:
                    amount_precision = 18

                kind = infer_asset_kind(sym, chain_code, chain_name)
                if kind == AssetKind.CRYPTO and dep_conf < 1:
                    dep_conf = 1
                    wd_conf = max(wd_conf, dep_conf)

                out.append(_Row(
                    asset_code=sym, asset_name=asset_name,
                    chain_code=chain_code, chain_name=chain_name,
                    AD=can_dep, AW=can_wd,
                    conf_dep=dep_conf, conf_wd=wd_conf,
                    dep_min=dep_min, dep_max=dep_max,
                    wd_min=wd_min, wd_max=wd_max,
                    dep_fee_pct=dep_fee_pct, dep_fee_fix=dep_fee_fix,
                    wd_fee_pct=wd_fee_pct, wd_fee_fix=wd_fee_fix,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    requires_memo=requires_memo,
                    amount_precision=amount_precision,
                    asset_kind=kind,
                    raw_meta=json_safe({"coin": coin, "chain": net}),
                ))
        return out

    @transaction.atomic
    def sync_assets(
        self,
        exchange: Exchange,
        *,
        timeout: int = 20,
        limit: int = 0,
        reconcile: bool = True,
        verbose: bool = False,
    ) -> AssetSyncStats:
        stats = AssetSyncStats()

        api_key, api_secret = get_any_enabled_keys(exchange)
        if not api_key or not api_secret:
            raise RuntimeError("MEXC: не найдены активные API-ключи для этого провайдера")

        try:
            payload = _http_get_json_signed(CAPITAL_CONFIG_URL, api_key, api_secret, timeout=timeout, retries=2)
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            raise RuntimeError(f"MEXC: ошибка запросов: {e}")

        rows = self._rows_from_payload(payload)
        if limit and limit > 0:
            rows = rows[:limit]

        seen: Set[Tuple[str, str]] = set()

        for r in rows:
            stats.processed += 1

            prec = int(r.amount_precision or 8)

            # --- фильтр по выводу ---
            # 1) минимальный вывод > 0
            # 2) минимальный вывод < 100_000
            wd_min_q = q_amount(r.wd_min, prec)
            if not (wd_min_q > q_amount(D(0), prec) and wd_min_q < q_amount(D(100_000), prec)):
                stats.skipped += 1
                continue  # полностью пропускаем монету/цепь

            # Доп. фильтр по фикс-комиссии вывода: ≤ 100_000 (иначе мусор)
            wd_fee_fix_q = q_amount(r.wd_fee_fix, prec)
            if wd_fee_fix_q >= q_amount(D(100_000), prec):
                stats.skipped += 1
                continue

            # прошла фильтр — учитываем как присутствующую
            seen.add((r.asset_code, r.chain_code))

            new_vals = dict(
                asset_name=r.asset_name,
                AD=bool(r.AD),
                AW=bool(r.AW),
                confirmations_deposit=int(r.conf_dep if (r.asset_kind == AssetKind.FIAT) or (r.conf_dep > 0) else 1),
                confirmations_withdraw=int(max(r.conf_dep if r.conf_dep > 0 else 1, r.conf_wd)),

                deposit_fee_percent=q_percent(r.dep_fee_pct),
                deposit_fee_fixed=q_amount(r.dep_fee_fix, prec),
                deposit_min=q_amount(r.dep_min, prec),
                deposit_max=q_amount(r.dep_max, prec),

                withdraw_fee_percent=q_percent(r.wd_fee_pct),
                withdraw_fee_fixed=q_amount(r.wd_fee_fix, prec),
                withdraw_min=wd_min_q,

                requires_memo=bool(r.requires_memo),
                is_stablecoin=bool(r.is_stable),
                amount_precision=prec,
                asset_kind=r.asset_kind,
                provider_symbol=r.asset_code,
                provider_chain=r.chain_code,
            )

            obj, created = ExchangeAsset.objects.get_or_create(
                exchange=exchange,
                asset_code=r.asset_code,
                chain_code=r.chain_code,
                defaults={**new_vals, "raw_metadata": json_safe(r.raw_meta), "chain_name": r.chain_name, "asset_name": r.asset_name},
            )
            if created:
                stats.created += 1
                continue

            changed: list[str] = []
            for f, v in new_vals.items():
                if getattr(obj, f) != v:
                    setattr(obj, f, v)
                    changed.append(f)

            if changed:
                obj.raw_metadata = json_safe(r.raw_meta)
                obj.save(update_fields=changed + ["raw_metadata", "updated_at"])
                stats.updated += 1
            else:
                stats.skipped += 1

        if reconcile:
            to_disable = []
            q = ExchangeAsset.objects.filter(exchange=exchange).only("id", "asset_code", "chain_code", "AD", "AW")
            for obj in q:
                key = (obj.asset_code, obj.chain_code)
                if key not in seen and (obj.AD or obj.AW):
                    to_disable.append(obj.id)
            if to_disable:
                ExchangeAsset.objects.filter(id__in=to_disable).update(
                    AD=False, AW=False,
                    status_note="Отключено: отсутствует в выдаче MEXC",
                    updated_at=timezone.now(),
                )
                stats.disabled = len(to_disable)

        if verbose:
            print(f"[MEXC] processed={stats.processed} created={stats.created} updated={stats.updated} skipped={stats.skipped} disabled={stats.disabled}")

        return stats
