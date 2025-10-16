from __future__ import annotations
import requests
from decimal import Decimal
from typing import Dict, Tuple
import time
from app_market.models.exchange import Exchange
from app_market.prices.publisher import publish_l1_code  # ← как у тебя

KU_BASE = "https://api.kucoin.com"
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
    /api/v2/symbols → {symbol: (BASE, QUOTE)} только для включённых рынков.
    Пример symbol: 'BTC-USDT'
    """
    r = requests.get(f"{KU_BASE}/api/v2/symbols", timeout=(4, 10))
    r.raise_for_status()
    d = r.json()
    items = (d.get("data") or [])
    out: Dict[str, Tuple[str, str]] = {}
    for it in items:
        if not it or not it.get("enableTrading"):
            continue
        sym = (it.get("symbol") or "").upper()  # BTC-USDT
        b = (it.get("baseCurrency") or "").upper()  # BTC
        q = (it.get("quoteCurrency") or "").upper()  # USDT
        if sym and b and q:
            out[sym] = (b, q)
    return out


def _tickers_all() -> Dict[str, dict]:
    """
    /api/v1/market/allTickers → {symbol: {...}}
    Внутри ticker: [{symbol, buy, sell, last, ...}], общий 'time' в мс.
    """
    r = requests.get(f"{KU_BASE}/api/v1/market/allTickers", timeout=(4, 10))
    r.raise_for_status()
    d = r.json()
    data = d.get("data") or {}
    ts_ms = int(data.get("time") or 0) or None
    arr = data.get("ticker") or []
    out: Dict[str, dict] = {}
    for it in arr:
        sym = (it.get("symbol") or "").upper()  # BTC-USDT
        if not sym:
            continue
        # приклеим ts к каждому элементу для единообразия
        it["_ts_ms"] = ts_ms
        out[sym] = it
    return out


def collect_spot(ex: Exchange, dry_run: bool = False) -> tuple[int, int]:
    """
    Собрать ВСЕ спот-тикеры KuCoin и опубликовать L1 «по кодам» в Redis.
    Возвращает (pushed, skipped).
    """
    sym_map = _symbols_spot_cached()  # symbol -> (BASE, QUOTE)
    ticks = _tickers_all()  # symbol -> {buy, sell, last, _ts_ms}

    pushed = skipped = 0
    exchange_kind = (ex.exchange_kind or "CEX")

    for sym, t in ticks.items():
        bq = sym_map.get(sym)
        if not bq:
            skipped += 1
            continue
        base, quote = bq

        try:
            # KuCoin: buy = best bid, sell = best ask
            bid = Decimal(t["buy"])
            ask = Decimal(t["sell"])
            last = Decimal(t["last"]) if t.get("last") else None
            ts_ms = int(t.get("_ts_ms") or 0) or None
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
                src_symbol=sym,  # например: BTC-USDT
                extras={"kucoin_v": "v1"},
            )
        pushed += 1

    return pushed, skipped
