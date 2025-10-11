from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Any, Iterable, Optional, Tuple, Set
from collections import Counter
from decimal import Decimal
import logging, random, time

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from app_market.models.exchange import Exchange
from app_market.models.exchange_asset import ExchangeAsset, AssetKind
from app_market.providers.global_slots import (
    acquire_global_slot,
    acquire_global_slot_blocking,
    release_global_slot,
    Slot,
)

from .numeric import (
    D, to_db_amount, to_db_percent, json_safe,
    U, infer_asset_kind, crypto_withdraw_guard, NO_CHAIN,
)

logger = logging.getLogger("app_market.sync")


# ───────────────────────────────────────────────────────────────────────────────
# Конфигурация поведения (из settings без .env)
# ───────────────────────────────────────────────────────────────────────────────
WRITE_ENABLED: bool = bool(getattr(settings, "PROVIDER_SYNC_WRITE_ENABLED", True))
LOCK_TTL: int = int(getattr(settings, "PROVIDER_SYNC_LOCK_TTL_SECONDS", 30 * 60))  # 30m
DEBOUNCE_SECONDS: int = int(getattr(settings, "PROVIDER_SYNC_DEBOUNCE_SECONDS", 5 * 60))  # 5m
DB_CHUNK_SIZE: int = int(getattr(settings, "PROVIDER_SYNC_DB_CHUNK_SIZE", 500))
FAIL_THRESHOLD: int = int(getattr(settings, "PROVIDER_SYNC_FAIL_THRESHOLD", 3))
CIRCUIT_TTL: int = int(getattr(settings, "PROVIDER_SYNC_CIRCUIT_TTL_SECONDS", 60 * 60))  # 1h
GLOBAL_WAIT_SECONDS: int = int(getattr(settings, "PROVIDER_SYNC_GLOBAL_WAIT_SECONDS", 0))  # ⟵ новое

# retry backoff base
_BACKOFF_S = (0.5, 1.0, 2.0)  # + джиттер [0..0.2]


# ───────────────────────────────────────────────────────────────────────────────
# Типы/контракты
# ───────────────────────────────────────────────────────────────────────────────
@dataclass
class AssetSyncStats:
    processed: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    disabled: int = 0


class ProviderAdapter(Protocol):
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


@dataclass
class ProviderRow:
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

    requires_memo: bool
    amount_precision: int
    is_stable: bool

    raw_meta: dict


class UnifiedProviderBase(ProviderAdapter):
    """
    Реализации обязаны переопределить:
      - fetch_payload(timeout) -> Any
      - iter_rows(payload) -> Iterable[ProviderRow]
    Всё остальное — типизация, кванты, upsert, reconcile, логирование — тут.
    """

    # --- опции политики / провайдерские хуки ---
    def policy_write_withdraw_max(self) -> bool:
        return True

    def provider_name_for_status(self) -> str:
        return self.code

    # --- тонкий провайдер должен реализовать ---
    def fetch_payload(self, *, timeout: int) -> Any:
        raise NotImplementedError

    def iter_rows(self, payload: Any) -> Iterable[ProviderRow]:
        raise NotImplementedError

    # --- служебные утилиты ---

    def _lock_key(self, exchange_id: int) -> str:
        return f"sync:{self.code}:{exchange_id}"

    def _last_key(self, exchange_id: int) -> str:
        return f"sync:last:{self.code}:{exchange_id}"

    def _fail_key(self, exchange_id: int) -> str:
        return f"sync:fail:{self.code}:{exchange_id}"

    def _circuit_key(self, exchange_id: int) -> str:
        return f"sync:circuit:{self.code}:{exchange_id}"

    def _sleep_backoff(self, attempt: int, retry_after: Optional[float] = None) -> None:
        # уважение Retry-After (секунды); иначе экспонента + джиттер
        if retry_after is not None:
            time.sleep(max(0.0, float(retry_after)))
            return
        base = _BACKOFF_S[min(attempt, len(_BACKOFF_S)-1)]
        time.sleep(base + random.uniform(0.0, 0.2))

    def _fetch_with_retries(self, *, timeout: int):
        last_exc = None
        for attempt in range(len(_BACKOFF_S) + 1):
            try:
                return self.fetch_payload(timeout=timeout)
            except Exception as e:  # ожидаем, что провайдер бросит HTTP-ошибку/исключение
                last_exc = e
                status = None
                retry_after = None
                resp = getattr(e, "response", None)
                if resp is not None:
                    status = getattr(resp, "status_code", None)
                    ra = getattr(resp, "headers", {}).get("Retry-After") if hasattr(resp, "headers") else None
                    if ra:
                        try:
                            retry_after = float(int(ra))
                        except Exception:
                            retry_after = None

                if status and (status == 429 or 500 <= int(status) < 600):
                    if attempt < len(_BACKOFF_S):
                        self._sleep_backoff(attempt, retry_after)
                        continue
                else:
                    if attempt < len(_BACKOFF_S):
                        self._sleep_backoff(attempt, None)
                        continue
                break
        raise last_exc  # если дошли сюда — исчерпали попытки

    # --- основной конвейер ---
    def sync_assets(
        self,
        exchange: Exchange,
        *,
        timeout: int = 20,
        limit: int = 0,
        reconcile: bool = True,
        verbose: bool = False,
    ) -> AssetSyncStats:

        t0 = time.perf_counter()
        stats = AssetSyncStats()
        changes = Counter()
        skip_reasons = Counter()

        ex_id = int(exchange.id)
        lock_key = self._lock_key(ex_id)
        last_key = self._last_key(ex_id)
        fail_key = self._fail_key(ex_id)
        circuit_key = self._circuit_key(ex_id)

        # circuit open?
        if cache.get(circuit_key):
            if verbose:
                print(f"[{self.code}] circuit open → пропуск")
            return stats

        # debounce (только для «полных» запусков — без limit и c reconcile)
        if limit == 0 and reconcile:
            last_ts = cache.get(last_key)
            if last_ts:
                delta = time.time() - float(last_ts)
                if delta < DEBOUNCE_SECONDS:
                    if verbose:
                        print(f"[{self.code}] дебаунс {int(DEBOUNCE_SECONDS - delta)}с → пропуск")
                    return stats

        # ── Глобальный лимит: ждём свободный слот при необходимости ────────────
        slot: Slot | None = None
        max_conc = int(getattr(settings, "PROVIDER_SYNC_GLOBAL_MAX_CONCURRENT", 0))
        if max_conc > 0:
            wait_s = int(GLOBAL_WAIT_SECONDS)
            slot = (
                acquire_global_slot_blocking(wait_s)
                if wait_s > 0 else
                acquire_global_slot()
            )
            if slot is None:
                if verbose:
                    print(f"[{self.code}] global limit reached → пропуск")
                logger.info("[%s] global_limit_reached", self.code)
                return stats

        # per-exchange lock
        if not cache.add(lock_key, "1", LOCK_TTL):
            if verbose:
                print(f"[{self.code}] lock существует → пропуск")
            if slot is not None:
                release_global_slot(slot)
            return stats

        present_raw: Set[Tuple[str, str]] = set()
        batch_count = 0

        try:
            payload = self._fetch_with_retries(timeout=timeout)
            rows = list(self.iter_rows(payload))
            if limit and limit > 0:
                rows = rows[:limit]

            def commit_needed():
                return (batch_count % DB_CHUNK_SIZE) == 0

            def upsert_row(r: ProviderRow) -> Optional[ExchangeAsset]:
                nonlocal stats, changes, skip_reasons, batch_count

                prec = int(r.amount_precision or 8)
                if prec < 0:
                    prec = 0
                if prec > int(getattr(settings, "DECIMAL_AMOUNT_DEC_PLACES", 10)):
                    prec = int(getattr(settings, "DECIMAL_AMOUNT_DEC_PLACES", 10))

                no_chain = (U(r.chain_code) == "")
                if no_chain:
                    kind_guess = infer_asset_kind(r.asset_code, "", "")
                    chain_db = "FIAT" if kind_guess == AssetKind.FIAT else NO_CHAIN
                    kind = kind_guess if kind_guess == AssetKind.FIAT else AssetKind.NOTDEFINED
                    AD = (kind == AssetKind.FIAT)
                    AW = (kind == AssetKind.FIAT)
                    conf_dep = 0
                    conf_wd = 0
                else:
                    kind = AssetKind.CRYPTO
                    chain_db = r.chain_code
                    AD = bool(r.AD) and (int(r.conf_dep) > 0)
                    AW = bool(r.AW) and (int(r.conf_wd) > 0)
                    conf_dep = int(r.conf_dep)
                    conf_wd = int(r.conf_wd)

                present_raw.add((r.asset_code, chain_db))

                if kind == AssetKind.CRYPTO:
                    ok, wd_min_q, wd_fee_fix_q = crypto_withdraw_guard(r.wd_min, r.wd_fee_fix, prec)
                    if not ok:
                        stats.processed += 1
                        stats.skipped += 1
                        skip_reasons["wd_guard"] += 1
                        return None
                else:
                    wd_min_q = to_db_amount(r.wd_min, prec)
                    wd_fee_fix_q = to_db_amount(r.wd_fee_fix, prec)

                dep_min_q = to_db_amount(r.dep_min, prec)
                dep_max_q = to_db_amount(r.dep_max, prec)
                wd_max_q = to_db_amount(r.wd_max, prec) if self.policy_write_withdraw_max() else to_db_amount(D(0), prec)

                dep_fee_pct_q = to_db_percent(r.dep_fee_pct)
                dep_fee_fix_q = to_db_amount(r.dep_fee_fix, prec)
                wd_fee_pct_q = to_db_percent(r.wd_fee_pct)

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

                stats.processed += 1

                if not WRITE_ENABLED:
                    return None

                obj = None
                obj_created = False
                obj_changed_fields: list[str] = []

                with transaction.atomic():
                    obj, obj_created = ExchangeAsset.objects.get_or_create(
                        exchange=exchange,
                        asset_code=r.asset_code,
                        chain_code=chain_db,
                        defaults={
                            **new_vals,
                            "raw_metadata": json_safe(r.raw_meta),
                            "chain_name": r.chain_name or chain_db,
                            **({"D": False, "W": False} if kind == AssetKind.FIAT else {}),
                        },
                    )

                    if obj_created:
                        stats.created += 1
                    else:
                        for f, v in new_vals.items():
                            if getattr(obj, f) != v:
                                setattr(obj, f, v)
                                obj_changed_fields.append(f)
                        if obj_changed_fields:
                            obj.raw_metadata = json_safe(r.raw_meta)
                            obj.save(update_fields=obj_changed_fields + ["raw_metadata", "updated_at"])
                            for f in obj_changed_fields:
                                changes[f] += 1
                            stats.updated += 1
                        else:
                            stats.skipped += 1

                batch_count += 1
                return obj

            for r in rows:
                upsert_row(r)

            if reconcile and WRITE_ENABLED:
                to_disable = []
                q = ExchangeAsset.objects.filter(exchange=exchange).only("id", "asset_code", "chain_code", "AD", "AW")
                for obj in q:
                    key = (obj.asset_code, obj.chain_code)
                    if key not in present_raw and (obj.AD or obj.AW):
                        to_disable.append(obj.id)

                if to_disable:
                    with transaction.atomic():
                        ExchangeAsset.objects.filter(id__in=to_disable).update(
                            AD=False, AW=False,
                            status_note=f"Отключено: отсутствует в выдаче {self.provider_name_for_status()}",
                            updated_at=timezone.now(),
                        )
                    stats.disabled = len(to_disable)

            cache.delete(fail_key)
            cache.set(last_key, time.time(), timeout=None)

        except Exception as e:
            fails = int(cache.get(fail_key) or 0) + 1
            cache.set(fail_key, fails, timeout=CIRCUIT_TTL)
            if fails >= FAIL_THRESHOLD:
                cache.set(circuit_key, True, timeout=CIRCUIT_TTL)

            logger.error(
                "sync_failed",
                extra={
                    "provider": self.code,
                    "exchange_id": ex_id,
                    "error": str(e),
                    "fails_in_row": fails,
                },
            )
            raise

        finally:
            cache.delete(lock_key)
            if slot is not None:
                release_global_slot(slot)

            dur_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "sync_done",
                extra={
                    "provider": self.code,
                    "exchange_id": ex_id,
                    "processed": stats.processed,
                    "created": stats.created,
                    "updated": stats.updated,
                    "skipped": stats.skipped,
                    "disabled": stats.disabled,
                    "duration_ms": dur_ms,
                    "skip_reason_wd_guard": skip_reasons.get("wd_guard", 0),
                    "write_enabled": WRITE_ENABLED,
                },
            )

            if verbose:
                print(
                    f"[{self.code}] processed={stats.processed} created={stats.created} "
                    f"updated={stats.updated} skipped={stats.skipped} disabled={stats.disabled} "
                    f"duration_ms={dur_ms}"
                )
                if changes:
                    top = ", ".join(f"{k}={v}" for k, v in changes.most_common(10))
                    print(f"[{self.code}] field changes breakdown: {top}")

        return stats
