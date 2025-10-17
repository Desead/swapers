from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Dict, Any, List

import logging
from django.db import transaction
from django.utils import timezone as dj_tz
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist

from app_market.models.exchange import Exchange, LiquidityProvider
from app_market.models.price import PriceL1
from .dump import write_daily_dump

# ───────────────────────────────────────────────────────────────────────────────
# ПРАЙС-СБОРЩИКИ
# ───────────────────────────────────────────────────────────────────────────────
from app_market.prices.price_bybit import collect_spot as bybit_collect_spot
from app_market.prices.price_whitebit import collect_spot as whitebit_collect_spot
from app_market.prices.price_kucoin import collect_spot as kucoin_collect_spot
from app_market.prices.price_mexc import collect_spot as mexc_collect_spot
from app_market.prices.price_htx import collect_spot as htx_collect_spot
from app_market.prices.price_rapira import collect_spot as rapira_collect_spot
from app_market.prices.price_twelvedata import collect_spot as twelvedata_collect_spot
from app_market.prices.price_openexchangerates import collect_spot as oer_collect_spot

# --- StatsError alias на уровне модуля (поддаётся monkeypatch) ---
try:
    from app_market.services.stats import StatsError as _StatsError
except Exception:
    class _StatsError(Exception):
        pass
StatsError = _StatsError

PRICE_COLLECTORS: Dict[str, Callable[[Exchange, bool], tuple[int, int]]] = {
    LiquidityProvider.BYBIT: bybit_collect_spot,
    LiquidityProvider.WHITEBIT: whitebit_collect_spot,
    LiquidityProvider.KUCOIN: kucoin_collect_spot,
    LiquidityProvider.MEXC: mexc_collect_spot,
    LiquidityProvider.HTX: htx_collect_spot,
    LiquidityProvider.RAPIRA: rapira_collect_spot,
    # «наличные» источники курсов — тоже лежат в prices/*
    LiquidityProvider.TWELVEDATA: twelvedata_collect_spot,
    LiquidityProvider.OpExRate: oer_collect_spot,
}

# ───────────────────────────────────────────────────────────────────────────────

@contextmanager
def _safe_logrecord_extra_created():
    """
    Временный патч logging.Logger.makeRecord:
    если в extra залетело 'created' — переименуем в '_created', чтобы не падать.
    """
    orig = logging.Logger.makeRecord

    def patched(self, name, level, fn, lno, msg, args, exc_info, func=None, extra=None, sinfo=None):
        if extra and isinstance(extra, dict) and "created" in extra:
            extra = dict(extra)
            extra["_created"] = extra.pop("created")
        return orig(self, name, level, fn, lno, msg, args, exc_info, func, extra, sinfo)

    logging.Logger.makeRecord = patched
    try:
        yield
    finally:
        logging.Logger.makeRecord = orig


def _get_exchange(provider: str) -> Exchange:
    """
    Берём Exchange строго по полю provider.
    Если конфигурация нарушена (0 или >1 записей), падаем явно.
    """
    try:
        return Exchange.objects.get(provider=provider)
    except ObjectDoesNotExist as e:
        raise RuntimeError(f"Exchange с provider={provider} не найден") from e
    except MultipleObjectsReturned as e:
        raise RuntimeError(f"Найдено несколько Exchange с provider={provider}") from e


# ───────────────────────────────────────────────────────────────────────────────
# ЗЕРКАЛО В АДМИНКУ: publish_l1_code → PriceL1 (не фатально)
# ───────────────────────────────────────────────────────────────────────────────
@contextmanager
def _mirror_prices_to_admin(exchange: Exchange, enabled: bool):
    """
    Если enabled=True, временно оборачиваем app_market.prices.publisher.publish_l1_code
    и пытаемся писать в PriceL1 синхронно с публикацией в Redis.
    Ошибки БД не ломают публикацию в Redis — только логируются.
    """
    batch: List[dict[str, Any]] = []
    if not enabled:
        yield batch
        return

    from app_market.prices import publisher as _pub
    original = _pub.publish_l1_code
    log = logging.getLogger("app_market.mirror")

    def _wrapped_publish(*, provider_id: int, exchange_kind: str,
                         base_code: str, quote_code: str,
                         bid, ask, last=None, ts_src_ms: int | None = None,
                         src_symbol: str = "", extras: dict | None = None) -> str:
        # 1) публикация в Redis (критичный канал)
        ev_id = original(provider_id=provider_id, exchange_kind=exchange_kind,
                         base_code=base_code, quote_code=quote_code,
                         bid=bid, ask=ask, last=last, ts_src_ms=ts_src_ms,
                         src_symbol=src_symbol, extras=extras)

        # 2) зеркало в БД (best-effort)
        try:
            ts_src = dj_tz.now()
            if ts_src_ms:
                try:
                    ts_src = datetime.fromtimestamp(ts_src_ms / 1000.0, tz=timezone.utc)
                except Exception:
                    ts_src = dj_tz.now()

            with transaction.atomic():
                PriceL1.objects.create(
                    provider=exchange,
                    src_symbol=src_symbol or f"{base_code}{quote_code}",
                    src_base_code=base_code,
                    src_quote_code=quote_code,
                    bid=bid, ask=ask, last=last,
                    ts_src=ts_src,
                    extras=extras or {},
                )
        except Exception:
            log.exception("PriceL1 mirror failed for %s %s/%s", exchange, base_code, quote_code)

        # 3) нормализованный publish-пакет (для дампа)
        batch.append({
            "base": base_code, "quote": quote_code,
            "bid": str(bid), "ask": str(ask),
            "last": "" if last is None else str(last),
            "ts_src_ms": ts_src_ms, "src_symbol": src_symbol,
            "extras": extras or {},
        })
        return ev_id

    _pub.publish_l1_code = _wrapped_publish  # patch
    try:
        yield batch
    finally:
        _pub.publish_l1_code = original


# ───────────────────────────────────────────────────────────────────────────────
# PUBLIC API (runner вызывает эти функции)
# ───────────────────────────────────────────────────────────────────────────────
def run_wallet_assets(*, provider: str, adapter, dump_raw: bool = False, **_kwargs) -> dict:
    """
    Синхронизируем активы по провайдеру (UnifiedProviderBase.sync_assets()).
    """
    ex = _get_exchange(provider)

    # Сырой дамп: если адаптер поддерживает fetch_payload (части нужен ._exchange)
    raw_dump_path = None
    if dump_raw:
        try:
            setattr(adapter, "_exchange", ex)  # контракт некоторых адаптеров
            payload = adapter.fetch_payload(timeout=20)
            raw_dump_path = write_daily_dump("wallet", provider, payload)
        except Exception:
            raw_dump_path = None
        finally:
            if hasattr(adapter, "_exchange"):
                setattr(adapter, "_exchange", None)

    # Основной пайплайн записи в БД
    with _safe_logrecord_extra_created():
        stats = adapter.sync_assets(exchange=ex, timeout=20, limit=0, reconcile=True, verbose=False)

    return {
        "provider": provider,
        "exchange_id": ex.id,
        "processed": stats.processed,
        "created": stats.created,
        "updated": stats.updated,
        "skipped": stats.skipped,
        "disabled": stats.disabled,
        "raw_dump": str(raw_dump_path) if raw_dump_path else "",
    }


def run_prices(*, provider: str, dump_raw: bool = False, mirror_to_admin: bool = False, **_kwargs) -> dict:
    """
    Собираем ВСЕ L1-цены для провайдера (price_*:collect_spot), публикуем в Redis,
    опционально зеркалим их в БД (PriceL1), и при необходимости кладём JSON-дамп.
    """
    ex = _get_exchange(provider)
    collector = PRICE_COLLECTORS.get(provider)
    if not collector:
        raise RuntimeError(f"{provider}: для цен нет коллектор-функции")

    # Зеркало в админку — получаем ссылку на «живой» список batch
    with _mirror_prices_to_admin(ex, enabled=bool(mirror_to_admin)) as batch:
        pushed, skipped = collector(ex, dry_run=False)

    raw_dump_path = None
    if dump_raw:
        payload: dict[str, Any] = {
            "published": batch,
            "meta": {"provider": provider, "generated_at": dj_tz.now().isoformat()},
        }
        raw_dump_path = write_daily_dump("prices", provider, payload)

    return {
        "provider": provider,
        "exchange_id": ex.id,
        "pushed": int(pushed),
        "skipped": int(skipped),
        "raw_dump": str(raw_dump_path) if raw_dump_path else "",
        "mirrored_to_admin": bool(mirror_to_admin),
    }


def run_stats(*, provider: str, dump_raw: bool = False, **_kwargs) -> dict:
    """
    Собираем статистику провайдера и добавляем снимок в Exchange.stats_history.
    Если для провайдера статистика ещё не реализована (StatsError) — аккуратно пропускаем.
    """
    ex = _get_exchange(provider)
    from app_market.services.stats import collect_exchange_stats

    try:
        snap = collect_exchange_stats(ex, timeout=20)
    except StatsError as e:
        payload = {
            "provider": provider,
            "exchange_id": ex.id,
            "skipped": True,
            "reason": str(e),
        }
        if dump_raw:
            write_daily_dump("stats", provider, payload)
        return payload

    raw_dump_path = write_daily_dump("stats", provider, snap) if dump_raw else None
    return {
        "provider": provider,
        "exchange_id": ex.id,
        "snapshot_at": snap.get("run_at", ""),
        "raw_dump": str(raw_dump_path) if raw_dump_path else "",
    }
