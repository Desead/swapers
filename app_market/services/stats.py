# app_market/services/stats.py
from __future__ import annotations

from django.utils import timezone as dj_tz

from app_main.models import SiteSetup
from app_market.models import Exchange
from app_market.models.exchange import ExchangeKind, LiquidityProvider


class StatsError(Exception):
    pass


def _now_iso() -> str:
    return dj_tz.now().isoformat()


def _parse_csv_upper(s: str) -> list[str]:
    raw = (s or "").strip()
    if not raw:
        return []
    parts = [p.strip().upper() for p in raw.replace(";", ",").split(",") if p.strip()]
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


def _limit_to_max_length(value_list: list[str], max_len: int) -> str:
    result, total = [], 0
    for i, sym in enumerate(value_list):
        chunk = (", " if i else "") + sym
        if total + len(chunk) <= max_len:
            result.append(sym)
            total += len(chunk)
        else:
            break
    return ", ".join(result)


def collect_exchange_stats(exchange: Exchange, *, timeout: int = 20) -> dict:
    """
    Делегатор: вызывает сборщик для конкретного провайдера, формирует снимок (wallet, markets),
    добавляет снимок в exchange.stats_history и ПРИ НЕЗАПОЛНЕННОМ поле stablecoin
    — заполняет его списком всех стейблов (в порядке убывания популярности правых валют).
    """
    if exchange.exchange_kind != ExchangeKind.CEX:
        raise StatsError(f"Тип провайдера пока не поддержан: {exchange.exchange_kind}")

    provider = exchange.provider

    if provider == LiquidityProvider.MEXC:
        from .stat_mexc import collect_stats_for_exchange
        wallet, markets = collect_stats_for_exchange(exchange, timeout=timeout)

    elif provider == LiquidityProvider.BYBIT:
        from .stat_bybit import collect_stats_for_exchange
        wallet, markets = collect_stats_for_exchange(exchange, timeout=timeout)

    elif provider == LiquidityProvider.KUCOIN:
        from .stat_kucoin import collect_stats_for_exchange
        wallet, markets = collect_stats_for_exchange(exchange, timeout=timeout)

    elif provider == LiquidityProvider.HTX:
        from .stat_htx import collect_stats_for_exchange
        wallet, markets = collect_stats_for_exchange(exchange, timeout=timeout)
    elif provider == LiquidityProvider.WHITEBIT:
        from .stat_whitebit import collect_stats_for_exchange
        wallet, markets = collect_stats_for_exchange(exchange, timeout=timeout)
    else:
        raise StatsError(f"{provider}: сбор статистики ещё не реализован")

    # --- формируем снимок ---
    snap = {
        "run_at": _now_iso(),
        "kind": exchange.exchange_kind,
        "provider": provider,
        "wallet": wallet,
        "markets": markets,
    }

    # --- авто-установка списка стейблов ТОЛЬКО если поле ещё пустое ---
    changed_stable = False
    if not (exchange.stablecoin or "").strip():
        cfg_stables = set(_parse_csv_upper(SiteSetup.get_solo().stablecoins))
        stable_list: list[str] = []
        for row in (markets.get("quote_popularity") or []):
            q = (row.get("quote") or "").strip().upper()
            if q and q in cfg_stables and q not in stable_list:
                stable_list.append(q)

        if stable_list:
            field = exchange._meta.get_field("stablecoin")
            max_len = getattr(field, "max_length", 255) or 255
            new_value = _limit_to_max_length(stable_list, max_len)
            if new_value:
                exchange.stablecoin = new_value
                changed_stable = True

    # --- сохранить историю + (возможный) stablecoin одним save() ---
    hist = list(exchange.stats_history or [])
    hist.append(snap)
    exchange.stats_history = hist
    update_fields = ["stats_history"] + (["stablecoin"] if changed_stable else [])
    exchange.save(update_fields=update_fields)

    return snap


def ensure_initial_stats(exchange: Exchange, *, timeout: int = 20) -> bool:
    """
    Если у провайдера ещё нет снимков — делает первый (одноразово).
    """
    if exchange.stats_history:
        return False
    try:
        collect_exchange_stats(exchange, timeout=timeout)
        return True
    except Exception:
        return False
