# app_market/services/stat_kucoin.py
from __future__ import annotations

from collections import Counter
import requests

from app_market.models import Exchange

KUCOIN_REST = "https://api.kucoin.com"


# ---------- MARKETS (public) ----------

def _fetch_exchange_info(timeout: int = 15) -> list[dict]:
    """
    GET /api/v2/symbols  (public)
    Ожидаем data: [ { baseCurrency, quoteCurrency, enableTrading, symbol, market? } ... ]
    """
    url = f"{KUCOIN_REST}/api/v2/symbols"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    data = r.json() or {}
    return (data.get("data") or [])


def _truthy(v) -> bool:
    s = str(v).strip().lower()
    return v is True or s in {"1", "true", "yes", "enabled", "enable", "open", "trading"}


def _normalize_pairs_counts(items: list[dict]) -> dict:
    bases, quotes = set(), set()
    quote_counter: Counter[str] = Counter()
    pairs_total = 0

    for it in items or []:
        # Фильтруем неактивные
        if it.get("enableTrading") is False or str(it.get("enableTrading")).strip().lower() in {"false", "0", "disabled"}:
            continue

        base = (it.get("baseCurrency") or "").strip().upper()
        quote = (it.get("quoteCurrency") or "").strip().upper()

        # Fallback: symbol вида BTC-USDT
        if not base or not quote:
            sym = (it.get("symbol") or "").strip().upper()
            if "-" in sym:
                parts = sym.split("-", 1)
                if len(parts) == 2:
                    base, quote = parts[0].strip(), parts[1].strip()

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
    GET /api/v3/currencies  (public)
    Ожидаем data: [ { currency, chains:[{ isDepositEnabled, isWithdrawEnabled, ... }] } ... ]
    """
    url = f"{KUCOIN_REST}/api/v3/currencies"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    data = r.json() or {}
    return (data.get("data") or [])


def _normalize_wallet_counts(items: list[dict]) -> dict:
    total, dep, wd = set(), set(), set()

    for it in items or []:
        sym = (it.get("currency") or "").strip().upper()
        if not sym:
            continue
        total.add(sym)

        chains = it.get("chains") or []
        for ch in chains:
            if _truthy(ch.get("isDepositEnabled")):
                dep.add(sym)
            if _truthy(ch.get("isWithdrawEnabled")):
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
    Возвращает (wallet, markets) для KuCoin.
    Кошелёк: /api/v3/currencies (public), Маркет: /api/v2/symbols (public).
    """
    wallet_raw = _fetch_currencies(timeout=timeout)
    wallet = _normalize_wallet_counts(wallet_raw)

    items = _fetch_exchange_info(timeout=timeout)
    markets = _normalize_pairs_counts(items)

    return wallet, markets
