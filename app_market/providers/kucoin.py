from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Set, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from django.db import transaction
from django.utils import timezone

from app_market.models.exchange import Exchange
from app_market.models.exchange_asset import ExchangeAsset, AssetKind
from app_main.models import SiteSetup
from .base import ProviderAdapter, AssetSyncStats

UA = "swapers-sync/1.0 (+https://github.com/Desead/swapers)"
# KuCoin public
KUC_BASE = "https://api.kucoin.com"
CURRENCIES_URL = f"{KUC_BASE}/api/v3/currencies"


# --- helpers --------------------------------------------------------------

def _http_get_json(url: str, timeout: int = 20) -> Any:
    req = Request(url, headers={"User-Agent": UA})
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


def _upper(s: Optional[str]) -> str:
    return (s or "").strip().upper()


def _disp(s: Optional[str]) -> str:
    return (s or "").strip()


def _json_safe(o: Any) -> Any:
    """Decimal → str; dict/list → рекурсивно."""
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
    # у тебя уже есть метод-хелпер; если его нет — fallback на текстовое поле
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


# --- adapter --------------------------------------------------------------

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


class KucoinAdapter:
    code = "KUCOIN"

    def _fetch_public(self, *, timeout: int) -> list[dict]:
        """
        GET /api/v3/currencies
        Ответ: {"code":"200000","data":[{currency,name,precision,isDepositEnabled,isWithdrawEnabled,chains:[...]},...]}
        """
        data = _http_get_json(CURRENCIES_URL, timeout=timeout)
        if isinstance(data, dict):
            return list(data.get("data") or [])
        return []

    def _rows_from_public(self, payload: list[dict]) -> list[_Row]:
        stables = _stable_set_from_sitesetup()
        memo_chains = _memo_required_chains_from_site()

        rows: list[_Row] = []

        for item in payload:
            sym = _upper(item.get("currency"))
            if not sym:
                continue
            asset_name = _disp(item.get("name")) or sym
            chains = item.get("chains") or []

            # Без chains трактуем как FIAT (виртуальная сеть FIAT)
            if not chains:
                AD = _B(item.get("isDepositEnabled"))
                AW = _B(item.get("isWithdrawEnabled"))
                conf_dep = int(item.get("depositConfirmations") or item.get("confirms") or 0)
                conf_wd = int(item.get("withdrawConfirmations") or conf_dep)
                conf_dep, conf_wd = _ensure_wd_conf_ge_dep(conf_dep, conf_wd)
                # для крипты — минимум 1 подтверждение; FIAT — можно 0, но мы ставим 0
                # здесь считаем как FIAT
                amount_precision = int(item.get("precision") or 8)

                rows.append(
                    _Row(
                        asset_code=sym,
                        asset_name=asset_name,
                        chain_code="FIAT",
                        chain_display="FIAT",
                        AD=AD,
                        AW=AW,
                        conf_dep=conf_dep,
                        conf_wd=conf_wd,
                        dep_min=_D(item.get("depositMinSize")),
                        dep_max=_D(item.get("depositMaxSize")),
                        wd_min=_D(item.get("withdrawMinSize")),
                        wd_max=_D(item.get("withdrawMaxSize")),
                        dep_fee_pct=_D(0),
                        dep_fee_fix=_D(0),
                        wd_fee_pct=_D(0),
                        wd_fee_fix=_D(item.get("withdrawalMinFee") or item.get("withdrawFee") or 0),
                        is_stable=(sym in stables) or (_upper(asset_name) in stables),
                        requires_memo=False,
                        amount_precision=amount_precision,
                        raw_meta=_json_safe(item),
                    )
                )
                continue

            # По цепочкам
            for ch in chains:
                chain_name = ch.get("chainName") or ch.get("name") or ""
                chain_code = _upper(chain_name) or "NATIVE"
                chain_disp = chain_name or chain_code

                can_dep = _B(ch.get("isDepositEnabled"))
                can_wd = _B(ch.get("isWithdrawEnabled"))
                conf_dep = int(ch.get("confirmations") or ch.get("confirms") or 0)
                conf_wd = int(ch.get("withdrawConfirmations") or conf_dep)
                conf_dep, conf_wd = _ensure_wd_conf_ge_dep(conf_dep, conf_wd)

                # Для крипто-активов подтверждения депозита не могут быть 0
                if conf_dep < 1:
                    conf_dep = 1
                    if conf_wd < conf_dep:
                        conf_wd = conf_dep

                wd_fee_fix = _D(ch.get("withdrawalMinFee") or ch.get("withdrawFee") or 0)
                wd_min = _D(ch.get("withdrawMinSize") or 0)
                wd_max = _D(ch.get("withdrawMaxSize") or 0)
                dep_min = _D(ch.get("depositMinSize") or 0)
                dep_max = _D(ch.get("depositMaxSize") or 0)

                requires_memo = _B(ch.get("isMemoRequired") or ch.get("needTag")) or (chain_code in memo_chains) or (_upper(chain_disp) in memo_chains)

                amount_precision = int(ch.get("precision") or item.get("precision") or 8)

                rows.append(
                    _Row(
                        asset_code=sym,
                        asset_name=asset_name,
                        chain_code=chain_code,
                        chain_display=chain_disp,
                        AD=can_dep,
                        AW=can_wd,
                        conf_dep=conf_dep,
                        conf_wd=conf_wd,
                        dep_min=dep_min,
                        dep_max=dep_max,
                        wd_min=wd_min,
                        wd_max=wd_max,
                        dep_fee_pct=_D(0),
                        dep_fee_fix=_D(0),
                        wd_fee_pct=_D(0),
                        wd_fee_fix=wd_fee_fix,
                        is_stable=(sym in stables) or (_upper(asset_name) in stables),
                        requires_memo=requires_memo,
                        amount_precision=amount_precision,
                        raw_meta=_json_safe({"asset": item, "chain": ch}),
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
        Публичный синк активов KuCoin. Приватные уточнения комиссий можно добавить позже
        (приоритет приватных над публичными), но публичные данные уже содержат minFee, min/max и статусы.
        """
        stats = AssetSyncStats()

        # 1) загрузить публичные currencies
        try:
            payload = self._fetch_public(timeout=timeout)
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            raise RuntimeError(f"KuCoin: ошибка запросов: {e}")

        # 2) разложить в uniform rows
        rows = self._rows_from_public(payload)
        if limit and limit > 0:
            rows = rows[:limit]

        # 3) upsert в БД (аналогично whitebit)
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

        # 4) reconcile: те, кого нет в seen — отключаем AD/AW (ручные D/W не трогаем)
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

        return stats
