from __future__ import annotations
import requests
from decimal import Decimal
from typing import Dict, Tuple
import time
from app_market.models.exchange import Exchange
from app_market.prices.publisher import publish_l1_code

BYBIT_BASE = "https://api.bybit.com"
# кэш
_SYMBOLS_CACHE = {"data": {}, "next_at": 0.0}
_SYMBOLS_TTL_SEC = 600


def _symbols_spot_cached() -> Dict[str, Tuple[str, str]]:
    now = time.time()
    if now < _SYMBOLS_CACHE["next_at"] and _SYMBOLS_CACHE["data"]:
        return _SYMBOLS_CACHE["data"]
    data = _symbols_spot()
    _SYMBOLS_CACHE["data"] = data
    _SYMBOLS_CACHE["next_at"] = now + _SYMBOLS_TTL_SEC
    return data


def _symbols_spot() -> Dict[str, Tuple[str, str]]:
    """
    /v5/market/instruments-info?category=spot → {symbol: (BASE, QUOTE)}
    """
    r = requests.get(f"{BYBIT_BASE}/v5/market/instruments-info",
                     params={"category": "spot"}, timeout=(4, 10))
    r.raise_for_status()
    d = r.json()
    items = (d.get("result") or {}).get("list") or []
    out: Dict[str, Tuple[str, str]] = {}
    for it in items:
        sym = (it.get("symbol") or "").upper()
        b = (it.get("baseCoin") or "").upper()
        q = (it.get("quoteCoin") or "").upper()
        if sym and b and q:
            out[sym] = (b, q)
    return out


def _tickers_spot() -> Dict[str, dict]:
    """
    /v5/market/tickers?category=spot → {symbol: {... bid1Price, ask1Price, lastPrice, time ...}}
    """
    r = requests.get(f"{BYBIT_BASE}/v5/market/tickers",
                     params={"category": "spot"}, timeout=(4, 10))
    r.raise_for_status()
    d = r.json()
    items = (d.get("result") or {}).get("list") or []
    return {(it.get("symbol") or "").upper(): it for it in items if it.get("symbol")}


def collect_spot(ex: Exchange, dry_run: bool = False) -> tuple[int, int]:
    """
    Собрать ВСЕ спот-тикеры Bybit и опубликовать L1 «по кодам» (BASE/QUOTE) в Redis.
    Возвращает (pushed, skipped).
    """
    sym_map = _symbols_spot_cached()
    ticks = _tickers_spot()

    pushed = skipped = 0
    exchange_kind = (ex.exchange_kind or "CEX")

    for sym, tick in ticks.items():
        bq = sym_map.get(sym)
        if not bq:
            skipped += 1
            continue

        base, quote = bq
        try:
            bid = Decimal(tick["bid1Price"])
            ask = Decimal(tick["ask1Price"])
            last = Decimal(tick.get("lastPrice")) if tick.get("lastPrice") else None
            ts_ms = int(tick.get("time") or 0) or None
        except Exception:
            skipped += 1
            continue

        if not dry_run:
            publish_l1_code(
                provider_id=ex.id,
                exchange_kind=exchange_kind,
                base_code=base,
                quote_code=quote,
                bid=bid,
                ask=ask,
                last=last,
                ts_src_ms=ts_ms,
                src_symbol=sym,
                extras={"bybit_v": "v5"},
            )
        pushed += 1

    return pushed, skipped
