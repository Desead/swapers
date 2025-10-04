# app_market/providers/bybit.py
from __future__ import annotations

import json
import time
import hmac
import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Set, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from django.db import transaction
from django.utils import timezone

from app_market.models.exchange import Exchange
from app_market.models.exchange_asset import ExchangeAsset, AssetKind
from app_market.models.account import ExchangeApiKey
from app_main.models import SiteSetup
from .base import ProviderAdapter, AssetSyncStats

UA = "swapers-sync/1.0 (+https://github.com/Desead/swapers)"
BYBIT_BASE = "https://api.bybit.com"
COIN_INFO_URL = f"{BYBIT_BASE}/v5/asset/coin/query-info"
RECV_WINDOW = "5000"  # ms


# ---------- helpers ----------

def _http_get_json(url: str, headers: Dict[str, str], timeout: int = 20) -> Any:
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def _D(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if x in (None, "", "0E-10"):
        return Decimal("0")
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _B(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    if isinstance(x, str):
        v = x.strip().lower()
        return v in {"1", "true", "yes", "y", "on"}
    return False


def _U(s: Optional[str]) -> str:
    return (s or "").strip().upper()


def _disp(s: Optional[str]) -> str:
    return (s or "").strip()


def _json_safe(o: Any) -> Any:
    """Приводим объект к JSON-сериализуемому виду (Decimal->str, рекурсивно)."""
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
    if hasattr(ss, "get_memo_required_chains_set"):
        try:
            return set(ss.get_memo_required_chains_set())  # type: ignore[attr-defined]
        except Exception:
            pass
    txt = (getattr(ss, "memo_required_chains", "") or "").strip()
    if not txt:
        return set()
    return {p.strip().upper() for p in txt.replace(";", ",").split(",") if p.strip()}


def _ensure_wd_conf_ge_dep(dep_conf: int, wd_conf: int) -> tuple[int, int]:
    if wd_conf < dep_conf:
        wd_conf = dep_conf
    return dep_conf, wd_conf


def _bybit_pct_to_percent(v: Any) -> Decimal:
    """
    Bybit отдаёт withdrawPercentageFee как долю (например, 0.022 = 2.2%).
    В наших полях проценты хранятся "в процентах" (2.2 означает 2.2%).
    """
    return _D(v) * Decimal("100")


def _get_any_enabled_keys(exchange: Exchange) -> tuple[Optional[str], Optional[str]]:
    rec = (
        ExchangeApiKey.objects
        .filter(exchange=exchange, is_enabled=True)
        .order_by("id")
        .first()
    )
    return ((rec.api_key or None), (rec.api_secret or None)) if rec else (None, None)


# ---------- internal row ----------

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


# ---------- adapter ----------

class BybitAdapter:
    code = "BYBIT"

    def _fetch_coin_info_signed(self, *, api_key: str, api_secret: str, timeout: int) -> list[dict]:
        """
        GET /v5/asset/coin/query-info с подписью (требуется: apiTimestamp, apiKey, apiSignature).
        Подписываем строку: timestamp + apiKey + recvWindow + queryString  (у нас queryString пуст).
        """
        ts = str(int(time.time() * 1000))
        query = ""  # без фильтра, чтобы получить ВСЕ монеты
        prehash = ts + api_key + RECV_WINDOW + query
        sign = hmac.new(api_secret.encode(), prehash.encode(), hashlib.sha256).hexdigest()

        headers = {
            "User-Agent": UA,
            "Accept": "application/json",
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
            "X-BAPI-SIGN": sign,
            "X-BAPI-SIGN-TYPE": "2",  # HMAC-SHA256
        }

        data = _http_get_json(COIN_INFO_URL, headers=headers, timeout=timeout)
        if not isinstance(data, dict):
            return []
        if int(data.get("retCode", -1)) != 0:
            # Пробрасываем сообщение об ошибке как исключение
            raise RuntimeError(f"Bybit API error: retCode={data.get('retCode')} retMsg={data.get('retMsg')}")
        result = data.get("result") or {}
        rows = result.get("rows") or []
        return list(rows) if isinstance(rows, list) else []

    def _rows_from_public(self, payload: list[dict]) -> list[_Row]:
        stables = _stable_set_from_sitesetup()
        memo_chains = _memo_required_chains_from_site()

        rows: list[_Row] = []

        for item in payload:
            sym = _U(item.get("coin"))
            if not sym:
                continue
            asset_name = _disp(item.get("name")) or sym
            remain_amount = _D(item.get("remainAmount"))  # макс. на транзакцию по монете (может отсутствовать)
            chains = item.get("chains") or []

            if not chains:
                # трактуем как FIAT (виртуальная цепь "FIAT")
                rows.append(
                    _Row(
                        asset_code=sym,
                        asset_name=asset_name,
                        chain_code="FIAT",
                        chain_display="FIAT",
                        AD=False,
                        AW=False,
                        conf_dep=0,
                        conf_wd=0,
                        dep_min=_D(0),
                        dep_max=_D(0),
                        wd_min=_D(0),
                        wd_max=remain_amount,
                        dep_fee_pct=_D(0),
                        dep_fee_fix=_D(0),
                        wd_fee_pct=_D(0),
                        wd_fee_fix=_D(0),
                        is_stable=(sym in stables) or (_U(asset_name) in stables),
                        requires_memo=False,
                        amount_precision=8,
                        raw_meta=_json_safe(item),
                    )
                )
                continue

            for ch in chains:
                chain_code = _U(ch.get("chain")) or "NATIVE"
                chain_disp = _disp(ch.get("chainType")) or chain_code

                can_dep = _B(ch.get("chainDeposit"))
                can_wd = _B(ch.get("chainWithdraw"))

                dep_conf = int(ch.get("confirmation") or 0)
                safe_conf = int(ch.get("safeConfirmNumber") or 0)
                dep_conf, wd_conf = _ensure_wd_conf_ge_dep(dep_conf, safe_conf)
                if dep_conf < 1:
                    dep_conf = 1
                    wd_conf = max(wd_conf, dep_conf)

                dep_min = _D(ch.get("depositMin") or 0)
                dep_max = _D(0)  # явного depositMax нет в этом ответе
                wd_min = _D(ch.get("withdrawMin") or 0)
                wd_max = remain_amount if remain_amount > 0 else _D(0)

                wd_fee_fix = _D(ch.get("withdrawFee") or 0)
                wd_fee_pct = _bybit_pct_to_percent(ch.get("withdrawPercentageFee") or 0)

                requires_memo = (chain_code in memo_chains) or (_U(chain_disp) in memo_chains)
                amount_precision = int(ch.get("minAccuracy") or 8)

                rows.append(
                    _Row(
                        asset_code=sym,
                        asset_name=asset_name,
                        chain_code=chain_code,
                        chain_display=chain_disp,
                        AD=can_dep,
                        AW=can_wd,
                        conf_dep=dep_conf,
                        conf_wd=wd_conf,
                        dep_min=dep_min,
                        dep_max=dep_max,
                        wd_min=wd_min,
                        wd_max=wd_max,
                        dep_fee_pct=_D(0),
                        dep_fee_fix=_D(0),
                        wd_fee_pct=wd_fee_pct,
                        wd_fee_fix=wd_fee_fix,
                        is_stable=(sym in stables) or (_U(asset_name) in stables),
                        requires_memo=requires_memo,
                        amount_precision=amount_precision,
                        raw_meta=_json_safe({"coin": item, "chain": ch}),
                    )
                )

        return rows

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
        """
        Синхронизация активов Bybit с подписанным запросом.
        """
        stats = AssetSyncStats()

        api_key, api_secret = _get_any_enabled_keys(exchange)
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

            defaults = dict(
                asset_name=r.asset_name,
                chain_display=r.chain_display,
                AD=bool(r.AD),
                AW=bool(r.AW),
                confirmations_deposit=int(r.conf_dep),
                confirmations_withdraw=int(max(r.conf_dep, r.conf_wd)),
                deposit_fee_percent=_D(r.dep_fee_pct),
                deposit_fee_fixed=_D(r.dep_fee_fix),
                deposit_min=_D(r.dep_min),
                deposit_max=_D(r.dep_max),
                deposit_min_usdt=_D(0),
                deposit_max_usdt=_D(0),
                withdraw_fee_percent=_D(r.wd_fee_pct),
                withdraw_fee_fixed=_D(r.wd_fee_fix),
                withdraw_min=_D(r.wd_min),
                withdraw_max=_D(r.wd_max),
                withdraw_min_usdt=_D(0),
                withdraw_max_usdt=_D(0),
                requires_memo=bool(r.requires_memo),
                is_stablecoin=bool(r.is_stable),
                amount_precision=int(r.amount_precision or 8),
                status_note="",
                provider_symbol=r.asset_code,
                provider_chain=r.chain_code,
                raw_metadata=_json_safe(r.raw_meta),
                last_synced_at=timezone.now(),
                asset_kind=AssetKind.CRYPTO if r.chain_code != "FIAT" else AssetKind.FIAT,
            )

            obj, created = ExchangeAsset.objects.get_or_create(
                exchange=exchange,
                asset_code=r.asset_code,
                chain_code=r.chain_code,
                defaults=defaults,
            )

            # крипта: минимум 1 подтверждение депозита
            if obj.asset_kind == AssetKind.CRYPTO and obj.confirmations_deposit == 0:
                obj.confirmations_deposit = 1
                if obj.confirmations_withdraw < obj.confirmations_deposit:
                    obj.confirmations_withdraw = obj.confirmations_deposit

            if created:
                stats.created += 1
            else:
                changed = False
                for fld, val in defaults.items():
                    if getattr(obj, fld) != val:
                        setattr(obj, fld, val)
                        changed = True
                if changed:
                    obj.updated_at = timezone.now()
                    obj.save()
                    stats.updated += 1
                else:
                    stats.skipped += 1

        # отключаем отсутствующие у провайдера (AD/AW); ручные D/W не трогаем
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

        return stats
