# app_market/services/stat_htx.py
from __future__ import annotations

from collections import Counter
import requests

from app_market.models import Exchange

# Исторически Huobi -> HTX; их публичные API доступны на huobi.pro/htx.com.
# Используем проверенный хост.
HTX_REST = "https://api.huobi.pro"


# ---------- MARKETS (public) ----------

def _fetch_exchange_info(timeout: int = 15) -> list[dict]:
    """
    GET /v1/common/symbols
    data: [{ "base-currency": "btc", "quote-currency": "usdt", "state": "online", ... }, ...]
    """
    url = f"{HTX_REST}/v1/common/symbols"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    data = r.json() or {}
    return data.get("data") or []


def _normalize_pairs_counts(items: list[dict]) -> dict:
    bases, quotes = set(), set()
    quote_counter: Counter[str] = Counter()
    pairs_total = 0

    for it in items or []:
        state = (it.get("state") or "").strip().lower()
        # активные/торгуемые
        if state and state not in {"online", "trading"}:
            continue

        base = (it.get("base-currency") or "").strip().upper()
        quote = (it.get("quote-currency") or "").strip().upper()
        if not base or not quote:
            continue

        bases.add(base)
        quotes.add(quote)
        quote_counter[quote] += 1
        pairs_total += 1

    coins_trade = sorted(bases | quotes)
    quote_popularity = [{"quote": q, "pairs": c} for q, c in quote_counter.most_common()]

    return {
        "pairs_total": pairs_total,
        "coins_trade_total": len(coins_trade),
        "base_coins_total": len(bases),
        "quote_coins_total": len(quotes),
        "quote_popularity": quote_popularity,
        "top_quote": quote_popularity[0]["quote"] if quote_popularity else None,
    }


# ---------- WALLET (public) ----------

def _fetch_currencies(timeout: int = 20) -> list[dict]:
    """
    GET /v2/reference/currencies
    data: [{ "currency":"btc", "chains":[{ "deposit-enabled":true, "withdraw-enabled":true, ...}, ...]}, ...]
    """
    url = f"{HTX_REST}/v2/reference/currencies"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    data = r.json() or {}
    return data.get("data") or []


def _truthy(v) -> bool:
    s = str(v).strip().lower()
    return v is True or s in {"1", "true", "yes", "enabled", "enable", "open", "available", "allowed", "normal"}


def _normalize_wallet_counts(items: list[dict]) -> dict:
    total, dep, wd = set(), set(), set()

    for it in items or []:
        sym = (it.get("currency") or "").strip().upper()
        if not sym:
            continue
        total.add(sym)

        chains = it.get("chains") or []
        for ch in chains:
            # поддерживаем разные варианты ключей у HTX
            d = ch.get("deposit-enabled", ch.get("depositStatus", ch.get("deposit_status")))
            w = ch.get("withdraw-enabled", ch.get("withdrawStatus", ch.get("withdraw_status")))
            if _truthy(d):
                dep.add(sym)
            if _truthy(w):
                wd.add(sym)

    return {
        "coins_total": len(total),
        "coins_deposit_enabled": len(dep),
        "coins_withdraw_enabled": len(wd),
        "coins_list": sorted(total),
    }


# ---------- public API ----------

def collect_stats_for_exchange(exchange: Exchange, *, timeout: int = 20) -> tuple[dict, dict]:
    """
    Возвращает (wallet, markets) для HTX.
    Оба эндпоинта — публичные.
    """
    wallet_raw = _fetch_currencies(timeout=timeout)
    wallet = _normalize_wallet_counts(wallet_raw)

    items = _fetch_exchange_info(timeout=timeout)
    markets = _normalize_pairs_counts(items)

    return wallet, markets
