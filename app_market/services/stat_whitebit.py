# app_market/services/stat_whitebit.py
from __future__ import annotations

from collections import Counter
import requests

from app_market.models import Exchange

WHITEBIT_REST = "https://whitebit.com/api/v4"


def _truthy(v) -> bool:
    s = str(v).strip().lower()
    return v is True or s in {"1", "true", "yes", "enabled", "enable", "open", "available", "active", "trading"}


# ---------- MARKETS (public) ----------

def _fetch_markets(timeout: int = 15) -> list[dict]:
    url = f"{WHITEBIT_REST}/public/markets"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return list(data or [])


def _normalize_pairs_counts(items: list[dict]) -> dict:
    bases, quotes = set(), set()
    quote_counter: Counter[str] = Counter()
    pairs_total = 0

    for it in items or []:
        if not isinstance(it, dict):
            continue
        enabled = it.get("tradesEnabled", it.get("trades_enabled", it.get("enabled", it.get("active", True))))
        if not _truthy(enabled):
            continue

        base = (it.get("stock") or it.get("base") or it.get("baseCurrency") or it.get("baseAsset") or "").strip().upper()
        quote = (it.get("money") or it.get("quote") or it.get("quoteCurrency") or it.get("quoteAsset") or "").strip().upper()

        if not base or not quote:
            sym = (it.get("name") or it.get("symbol") or "").strip().upper()
            for sep in ("_", "-", "/"):
                if sep in sym:
                    parts = sym.split(sep, 1)
                    if len(parts) == 2:
                        base = base or parts[0].strip()
                        quote = quote or parts[1].strip()
                    break

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

def _fetch_assets(timeout: int = 20):
    url = f"{WHITEBIT_REST}/public/assets"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _normalize_wallet_counts(data) -> dict:
    total, dep, wd = set(), set(), set()

    items: list[dict] = []
    if isinstance(data, dict):
        # {"BTC": {...}, "USDT": {...}} -> [{"symbol":"BTC", ...}, ...]
        for k, v in data.items():
            rec = {"symbol": str(k).upper()}
            if isinstance(v, dict):
                rec.update(v)
            items.append(rec)
    elif isinstance(data, list):
        # поддерживаем несколько форм:
        # 1) [{"symbol":"BTC", ...}, ...]
        # 2) [["BTC", {...}], ["USDT", {...}], ...]
        for entry in data:
            if isinstance(entry, dict):
                items.append(entry)
            elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                sym, meta = entry[0], entry[1]
                rec = {"symbol": str(sym).upper()}
                if isinstance(meta, dict):
                    rec.update(meta)
                items.append(rec)
            # иначе пропускаем мусор
    # остальные формы — игнорируем

    for it in items:
        if not isinstance(it, dict):
            continue

        sym = (it.get("symbol") or it.get("name") or it.get("asset") or it.get("currency") or "").strip().upper()
        if not sym:
            continue
        total.add(sym)

        nets = it.get("networks") or it.get("chains") or []
        if isinstance(nets, dict):
            nets = list(nets.values())
        if not isinstance(nets, list):
            nets = []

        for ch in nets:
            if not isinstance(ch, dict):
                continue
            d = ch.get("deposit_enabled", ch.get("depositEnable", ch.get("enableDeposit", ch.get("can_deposit", ch.get("chainDeposit")))))
            w = ch.get("withdraw_enabled", ch.get("withdrawEnable", ch.get("enableWithdraw", ch.get("can_withdraw", ch.get("chainWithdraw")))))
            if _truthy(d):
                dep.add(sym)
            if _truthy(w):
                wd.add(sym)

        # дублирующие флаги на уровне актива
        if _truthy(it.get("can_deposit")):
            dep.add(sym)
        if _truthy(it.get("can_withdraw")):
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
    Возвращает (wallet, markets) для WhiteBIT.
    Оба эндпоинта — публичные: /public/assets и /public/markets.
    """
    assets = _fetch_assets(timeout=timeout)
    wallet = _normalize_wallet_counts(assets)

    markets_raw = _fetch_markets(timeout=timeout)
    markets = _normalize_pairs_counts(markets_raw)

    return wallet, markets
