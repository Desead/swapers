from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Dict, Any, Optional

from django.db import transaction
from django.utils import timezone as dj_tz

from app_market.models.exchange import Exchange, LiquidityProvider
from app_market.models.price import PriceL1
from .dump import write_daily_dump

# ───────────────────────────────────────────────────────────────────────────────
# ПРАЙС-СБОРЩИКИ (используем твои готовые collect_spot)
# ───────────────────────────────────────────────────────────────────────────────
from app_market.prices.price_bybit import collect_spot as bybit_collect_spot
from app_market.prices.price_whitebit import collect_spot as whitebit_collect_spot
from app_market.prices.price_kucoin import collect_spot as kucoin_collect_spot
from app_market.prices.price_mexc import collect_spot as mexc_collect_spot
from app_market.prices.price_htx import collect_spot as htx_collect_spot
from app_market.prices.price_rapira import collect_spot as rapira_collect_spot
from app_market.prices.price_twelvedata import collect_spot as twelvedata_collect_spot
from app_market.prices.price_openexchangerates import collect_spot as oer_collect_spot

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

def _get_exchange(provider: str) -> Exchange:
    """
    Берём Exchange по коду провайдера (первый попавшийся, как у тебя в ingest).
    """
    qs = Exchange.objects.filter(provider=provider).order_by("id")
    if not qs.exists():
        raise RuntimeError(f"Exchange с provider={provider} не найден")
    return qs.first()

# ───────────────────────────────────────────────────────────────────────────────
# ЗЕРКАЛО В АДМИНКУ: обёртка над publish_l1_code → PriceL1
# ───────────────────────────────────────────────────────────────────────────────
@contextmanager
def _mirror_prices_to_admin(exchange: Exchange, enabled: bool):
    """
    Если enabled=True, временно оборачиваем app_market.prices.publisher.publish_l1_code
    и пишем в PriceL1 синхронно с публикацией в Redis.
    """
    if not enabled:
        yield
        return

    from app_market.prices import publisher as _pub
    original = _pub.publish_l1_code
    published_batch: list[dict[str, Any]] = []

    def _wrapped_publish(*, provider_id: int, exchange_kind: str,
                         base_code: str, quote_code: str,
                         bid, ask, last=None, ts_src_ms: int | None = None,
                         src_symbol: str = "", extras: dict | None = None) -> str:
        # 1) оригинальная публикация в Redis
        ev_id = original(provider_id=provider_id, exchange_kind=exchange_kind,
                         base_code=base_code, quote_code=quote_code,
                         bid=bid, ask=ask, last=last, ts_src_ms=ts_src_ms,
                         src_symbol=src_symbol, extras=extras)

        # 2) зеркало в БД (без истории комиссий — они опциональны)
        ts_src = dj_tz.now()
        try:
            if ts_src_ms:
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
        # 3) аккумулируем «нормализованный» publish-пакет — пригодится для dump
        published_batch.append({
            "base": base_code, "quote": quote_code,
            "bid": str(bid), "ask": str(ask),
            "last": "" if last is None else str(last),
            "ts_src_ms": ts_src_ms, "src_symbol": src_symbol,
            "extras": extras or {},
        })

        return ev_id

    _pub.publish_l1_code = _wrapped_publish  # patch
    try:
        yield
    finally:
        _pub.publish_l1_code = original
        # прикрепляем собранную пачку к контексту, чтобы run_prices мог её забрать
        setattr(_mirror_prices_to_admin, "_last_batch", published_batch)

def _drain_mirror_batch() -> list[dict[str, Any]]:
    batch = getattr(_mirror_prices_to_admin, "_last_batch", None)
    setattr(_mirror_prices_to_admin, "_last_batch", None)
    return list(batch or [])

# ───────────────────────────────────────────────────────────────────────────────
# PUBLIC API (runner вызывает эти функции)
# ───────────────────────────────────────────────────────────────────────────────
def run_wallet_assets(*, provider: str, adapter, dump_raw: bool = False, **_kwargs) -> dict:
    """
    Синхронизируем активы по провайдеру (используем твой UnifiedProviderBase.sync_assets()).
    """
    ex = _get_exchange(provider)

    # Dump RAW до/после — используем провайдерский fetch_payload (для некоторых нужен exchange)
    raw_dump_path = None
    if dump_raw:
        try:
            # аккуратно: некоторым адаптерам нужен ._exchange для fetch_payload (см. Bybit) :contentReference[oaicite:4]{index=4}
            setattr(adapter, "_exchange", ex)
            payload = adapter.fetch_payload(timeout=20)
            raw_dump_path = write_daily_dump("wallet", provider, payload)
        except Exception:
            raw_dump_path = None
        finally:
            # вернуть guard-ссылку
            if hasattr(adapter, "_exchange"):
                setattr(adapter, "_exchange", None)

    # Основной пайплайн записи в БД (upsert, reconcile и т.д. делает база)
    stats = adapter.sync_assets(exchange=ex, timeout=20, limit=0, reconcile=True, verbose=False)
    return {
        "provider": provider,
        "exchange_id": ex.id,
        "processed": getattr(stats, "processed", 0),
        "created": getattr(stats, "created", 0),
        "updated": getattr(stats, "updated", 0),
        "skipped": getattr(stats, "skipped", 0),
        "disabled": getattr(stats, "disabled", 0),
        "raw_dump": str(raw_dump_path) if raw_dump_path else "",
    }

def run_prices(*, provider: str, dump_raw: bool = False, mirror_to_admin: bool = False, **_kwargs) -> dict:
    """
    Собираем ВСЕ L1 цены для провайдера (через твои price_*:collect_spot), публикуем в Redis,
    опционально зеркалим их в БД для админки (PriceL1), и при необходимости кладём JSON-дамп.
    """
    ex = _get_exchange(provider)
    collector = PRICE_COLLECTORS.get(provider)
    if not collector:
        raise RuntimeError(f"{provider}: для цен нет коллектор-функции")

    # Включаем зеркало в админку (патчим publisher на время выполнения)
    with _mirror_prices_to_admin(ex, enabled=bool(mirror_to_admin)):
        pushed, skipped = collector(ex, dry_run=False)

    # Если просили — кладём дамп. Истинный «raw от API» у разных модулей разный;
    # соберём максимум доступного без инвазии: нормализованные publish-записи +,
    # если удастся — дернём «внутренние» _tickers/_symbols функции модуля.
    batch = _drain_mirror_batch()
    raw_dump_path = None
    if dump_raw:
        payload: dict[str, Any] = {
            "published": batch,
            "meta": {"provider": provider, "generated_at": dj_tz.now().isoformat()},
            "sources": {},
        }
        # попробовать добрать «сырые» выдачи из модулей (best effort)
        try:
            mod_map = {
                LiquidityProvider.BYBIT: "app_market.prices.price_bybit",
                LiquidityProvider.WHITEBIT: "app_market.prices.price_whitebit",
                LiquidityProvider.KUCOIN: "app_market.prices.price_kucoin",
                LiquidityProvider.MEXC: "app_market.prices.price_mexc",
                LiquidityProvider.HTX: "app_market.prices.price_htx",
                LiquidityProvider.RAPIRA: "app_market.prices.price_rapira",
                LiquidityProvider.TWELVEDATA: "app_market.prices.price_twelvedata",
                LiquidityProvider.OpExRate: "app_market.prices.price_openexchangerates",
            }
            import importlib
            mod = importlib.import_module(mod_map[provider])
            for name in dir(mod):
                if not name.startswith("_"):
                    continue
                if "cached" in name:  # пропустим кэши
                    continue
                fn = getattr(mod, name, None)
                if callable(fn) and fn.__code__.co_argcount == 0:
                    try:
                        payload["sources"][name] = fn()
                    except Exception:
                        pass
        except Exception:
            pass
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
    """
    ex = _get_exchange(provider)
    from app_market.services.stats import collect_exchange_stats
    snap = collect_exchange_stats(ex, timeout=20)

    raw_dump_path = write_daily_dump("stats", provider, snap) if dump_raw else None
    return {
        "provider": provider,
        "exchange_id": ex.id,
        "snapshot_at": snap.get("run_at", ""),
        "raw_dump": str(raw_dump_path) if raw_dump_path else "",
    }
