# app_market/collectors/tasks.py
from __future__ import annotations

import logging
from typing import Iterable, List, Sequence, Tuple

from django.apps import apps

from .dump import write_daily_dump
from .metrics import Counter, Timer
from .types import CapabilityResult, L1PriceDTO, MarketPairDTO, StatsSnapshot, WalletAssetDTO

log = logging.getLogger(__name__)


def _split_result(res: object) -> CapabilityResult:
    """
    Унификация форматов:
      - если адаптер вернул (items, raw) -> как есть
      - если только items -> (items, None)
    """
    if isinstance(res, tuple) and len(res) == 2:
        return res  # type: ignore
    return (res, None)  # type: ignore


# ---------------- WalletAssetsTask ----------------

def run_wallet_assets(*, provider: str, adapter, db_sink, dump_raw: bool, counter: Counter) -> List[WalletAssetDTO]:
    with Timer(counter, "fetch_wallet_assets"):
        res = adapter.wallet_assets()
    items, raw = _split_result(res)
    items = list(items)  # type: ignore
    counter.fetched = len(items)
    counter.normalized = len(items)

    # Дамп один раз в сутки
    if dump_raw and (raw is not None):
        if write_daily_dump(provider, "wallet-assets", raw):
            counter.dump_written += 1

    # Запись в БД (идемпотентный upsert)
    pushed = db_sink.upsert_many(provider, items)
    counter.pushed = int(pushed or 0)
    return items


# ---------------- PricesTask ----------------

def run_prices(*, provider: str, adapter, redis_sink, admin_mirror, dump_raw: bool, mirror_to_admin: bool,
               counter: Counter) -> List[L1PriceDTO]:
    with Timer(counter, "fetch_prices_spot"):
        res = adapter.prices_spot()
    items, raw = _split_result(res)
    items = list(items)  # type: ignore
    counter.fetched = len(items)
    counter.normalized = len(items)

    # Дамп
    if dump_raw and (raw is not None):
        if write_daily_dump(provider, "prices", raw):
            counter.dump_written += 1

    # Публикация в Redis
    pushed = redis_sink.push_many(provider, items)
    counter.pushed = int(pushed or 0)

    # Зеркало в админку (без истории)
    if mirror_to_admin:
        admin_mirror.upsert_many(provider, items)

    return items


# ---------------- StatsTask ----------------

def run_stats(*, provider: str, adapter, wallet_items: Sequence[WalletAssetDTO] | None,
              market_items: Sequence[MarketPairDTO] | None, dump_raw: bool, counter: Counter) -> StatsSnapshot:
    """
    «Лёгкая» статистика: сколько монет в кошельке, сколько рынков/пар,
    покрытие, топ QUOTE, простые дельты доступности ввода/вывода.
    Хранится внутри провайдера (как у вас сейчас).
    """
    # Получаем данные, если не переданы из предыдущих задач
    raw_wallet = None
    raw_markets = None

    if wallet_items is None:
        res_w = adapter.wallet_assets()
        wallet_items, raw_wallet = _split_result(res_w)
        wallet_items = list(wallet_items)  # type: ignore

    if market_items is None and hasattr(adapter, "markets"):
        try:
            res_m = adapter.markets()
            market_items, raw_markets = _split_result(res_m)
            market_items = list(market_items)  # type: ignore
        except Exception:
            market_items = []

    wallet_coins = len({(w.asset, w.network or "") for w in (wallet_items or [])})
    market_coins = len({(m.base, m.quote) for m in (market_items or [])})

    coverage_pct = 0.0
    if wallet_coins:
        # грубо: отношение уникальных базовых из рынков к уникальным asset из кошелька
        base_in_markets = {m.base for m in (market_items or [])}
        unique_assets = {w.asset for w in (wallet_items or [])}
        inter = len(base_in_markets & unique_assets)
        coverage_pct = round(100.0 * inter / max(1, len(unique_assets)), 2)

    # "топ quote" — топ-5 правых валют по частоте в markets
    from collections import Counter as PyCounter
    q_counter = PyCounter(m.quote for m in (market_items or []))
    top_quotes = [q for q, _ in q_counter.most_common(5)]

    # простые дельты доступности (in/out) — считаем по текущему состоянию
    deltas_inout = {
        "in_off": sum(1 for w in (wallet_items or []) if not w.in_enabled),
        "out_off": sum(1 for w in (wallet_items or []) if not w.out_enabled),
    }

    from datetime import datetime
    snap = StatsSnapshot(
        wallet_coins=wallet_coins,
        market_coins=market_coins,
        coverage_pct=coverage_pct,
        top_quotes=top_quotes,
        deltas_inout=deltas_inout,
        as_of=datetime.utcnow(),
        notes=None,
    )

    # Дамп «сырых» если надо
    if dump_raw:
        if raw_wallet is not None:
            write_daily_dump(provider, "stats-wallet", raw_wallet)
        if raw_markets is not None:
            write_daily_dump(provider, "stats-markets", raw_markets)

    # Пишем в «провайдера» (как у вас сейчас)
    try:
        Exchange = apps.get_model("app_market", "Exchange")
        obj = Exchange.objects.filter(provider=provider).first()
        if obj is not None:
            # ищем поле для хранения статистики
            # JSONField 'stats' или 'statistics' — мягко
            import json
            payload = {
                "wallet_coins": snap.wallet_coins,
                "market_coins": snap.market_coins,
                "coverage_pct": snap.coverage_pct,
                "top_quotes": snap.top_quotes,
                "deltas_inout": snap.deltas_inout,
                "as_of": snap.as_of.isoformat(),
            }
            if hasattr(obj, "stats"):
                obj.stats = payload  # type: ignore
                obj.save(update_fields=["stats"])
            elif hasattr(obj, "statistics"):
                obj.statistics = payload  # type: ignore
                obj.save(update_fields=["statistics"])
            else:
                log.debug("Exchange has no JSON stats field; skip saving snapshot.")
        else:
            log.debug("Exchange provider=%s not found; skip stats save.", provider)
    except Exception as e:
        log.exception("Failed to save StatsSnapshot for provider=%s: %s", provider, e)

    counter.pushed = 1
    return snap
