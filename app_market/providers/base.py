from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from decimal import Decimal
from typing import Any, Iterable, Optional, Tuple, Set
from collections import Counter

from django.db import transaction
from django.utils import timezone

from app_market.models.exchange import Exchange
from app_market.models.exchange_asset import ExchangeAsset, AssetKind

from .numeric import (
    D, to_db_amount, to_db_percent, json_safe,
    U, stable_set, memo_required_set, infer_asset_kind,
    crypto_withdraw_guard, NO_CHAIN,
)


@dataclass
class AssetSyncStats:
    processed: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    disabled: int = 0


class ProviderAdapter(Protocol):
    """
    Базовый протокол адаптера провайдера (ПЛ).
    Реализации обязаны иметь .code (строка, равная LiquidityProvider.<...>)
    и метод sync_assets().
    """
    code: str

    def sync_assets(
            self,
            exchange: Exchange,
            *,
            timeout: int = 20,
            limit: int = 0,
            reconcile: bool = True,
            verbose: bool = False,
    ) -> AssetSyncStats: ...


# --------- унифицированная строка от провайдера ---------
@dataclass
class ProviderRow:
    asset_code: str
    asset_name: str
    # Пустая строка = «без сетей»; база сама классифицирует FIAT/NOTDEFINED и выберет chain_code для БД
    chain_code: str
    chain_name: str

    # Автофлаги «как заявлено API» (до учёта подтверждений)
    AD: bool
    AW: bool

    # Подтверждения (0 допустимы)
    conf_dep: int
    conf_wd: int

    # Лимиты и комиссии (Decimal, необработанные)
    dep_min: Decimal
    dep_max: Decimal
    wd_min: Decimal
    wd_max: Decimal
    dep_fee_pct: Decimal
    dep_fee_fix: Decimal
    wd_fee_pct: Decimal
    wd_fee_fix: Decimal

    requires_memo: bool
    amount_precision: int
    is_stable: bool

    # Корневой объект из API (без дублирования сетей)
    raw_meta: dict


class UnifiedProviderBase(ProviderAdapter):
    """
    Тонкий провайдер реализует:
      - fetch_payload(timeout) -> Any
      - iter_rows(payload) -> Iterable[ProviderRow]

    Всё остальное (типизация, проверки, квантование, upsert, reconcile) — здесь.
    """

    # --- опции политики / провайдерские хуки ---

    def policy_write_withdraw_max(self) -> bool:
        """Писать ли withdraw_max в БД (по умолчанию да). MEXC может переопределить на False."""
        return True

    def provider_name_for_status(self) -> str:
        """Короткое название в статусе reconcile."""
        return self.code

    # --- тонкий провайдер должен реализовать ---

    def fetch_payload(self, *, timeout: int) -> Any:
        raise NotImplementedError

    def iter_rows(self, payload: Any) -> Iterable[ProviderRow]:
        raise NotImplementedError

    # --- общий конвейер ---

    @transaction.atomic
    def sync_assets(
            self,
            exchange: Exchange,
            *,
            timeout: int = 20,
            limit: int = 0,
            reconcile: bool = True,
            verbose: bool = False,
    ):
        stats = AssetSyncStats()
        change_counter = Counter()

        payload = self.fetch_payload(timeout=timeout)
        rows_iter = self.iter_rows(payload)
        rows = list(rows_iter)
        if limit and limit > 0:
            rows = rows[:limit]

        seen: Set[Tuple[str, str]] = set()

        for r in rows:
            stats.processed += 1
            prec = int(r.amount_precision or 8)

            # 01. Если сети нет => это не крипта: FIAT или NOTDEFINED
            no_chain = (U(r.chain_code) == "")
            if no_chain:
                kind = infer_asset_kind(r.asset_code, "", "")
                # 02-03. Автофлаги для безсетевых
                if kind == AssetKind.FIAT:
                    AD, AW = True, True
                    chain_db = "FIAT"
                else:
                    AD, AW = False, False
                    chain_db = NO_CHAIN
                conf_dep = 0
                conf_wd = 0
            else:
                # 06. Есть сеть → крипта
                kind = AssetKind.CRYPTO
                chain_db = r.chain_code
                # 08-11. Подтверждения только гасят операции; флаги независимы
                AD = bool(r.AD) and (int(r.conf_dep) > 0)
                AW = bool(r.AW) and (int(r.conf_wd) > 0)
                conf_dep = int(r.conf_dep)
                conf_wd = int(r.conf_wd)

            # Централизованные лимиты по криптовыводу — только для крипты
            if kind == AssetKind.CRYPTO:
                ok, wd_min_q, wd_fee_fix_q = crypto_withdraw_guard(r.wd_min, r.wd_fee_fix, prec)
                if not ok:
                    stats.skipped += 1
                    continue
            else:
                wd_min_q = to_db_amount(r.wd_min, prec)
                wd_fee_fix_q = to_db_amount(r.wd_fee_fix, prec)

            # Квантование всех прочих сумм/процентов
            dep_min_q = to_db_amount(r.dep_min, prec)
            dep_max_q = to_db_amount(r.dep_max, prec)
            wd_max_q = to_db_amount(r.wd_max, prec) if self.policy_write_withdraw_max() else to_db_amount(D(0), prec)

            dep_fee_pct_q = to_db_percent(r.dep_fee_pct)
            dep_fee_fix_q = to_db_amount(r.dep_fee_fix, prec)
            wd_fee_pct_q = to_db_percent(r.wd_fee_pct)

            seen.add((r.asset_code, chain_db))

            new_vals = dict(
                asset_name=r.asset_name,
                AD=AD,
                AW=AW,

                confirmations_deposit=conf_dep,
                confirmations_withdraw=conf_wd,

                deposit_min=dep_min_q,
                deposit_max=dep_max_q,

                withdraw_min=wd_min_q,
                withdraw_max=wd_max_q,

                deposit_fee_percent=dep_fee_pct_q,
                deposit_fee_fixed=dep_fee_fix_q,

                withdraw_fee_percent=wd_fee_pct_q,
                withdraw_fee_fixed=wd_fee_fix_q,

                requires_memo=bool(r.requires_memo),
                is_stablecoin=bool(r.is_stable),
                amount_precision=prec,
                asset_kind=kind,
                provider_symbol=r.asset_code,
                provider_chain=chain_db,
            )

            defaults = {
                **new_vals,
                "raw_metadata": json_safe(r.raw_meta),
                "chain_name": r.chain_name or chain_db,
                "asset_name": r.asset_name,
            }
            # 02. Новые FIAT — ручные флаги D/W сбрасываем в False (только при создании)
            if kind == AssetKind.FIAT:
                defaults.update({"D": False, "W": False})

            obj, created = ExchangeAsset.objects.get_or_create(
                exchange=exchange,
                asset_code=r.asset_code,
                chain_code=chain_db,
                defaults=defaults,
            )

            if created:
                stats.created += 1
            else:
                changed = []
                for f, v in new_vals.items():
                    if getattr(obj, f) != v:
                        setattr(obj, f, v)
                        changed.append(f)
                if changed:
                    obj.raw_metadata = json_safe(r.raw_meta)
                    obj.save(update_fields=changed + ["raw_metadata", "updated_at"])
                    for f in changed:
                        change_counter[f] += 1
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
                    status_note=f"Отключено: отсутствует в выдаче {self.provider_name_for_status()}",
                    updated_at=timezone.now(),
                )
                stats.disabled = len(to_disable)

        if verbose:
            print(
                f"[{self.code}] processed={stats.processed} created={stats.created} updated={stats.updated} skipped={stats.skipped} disabled={stats.disabled}")
            if change_counter:
                top = ", ".join(f"{k}={v}" for k, v in change_counter.most_common(10))
                print(f"[{self.code}] field changes breakdown: {top}")

        return stats
