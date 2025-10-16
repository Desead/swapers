from __future__ import annotations
import requests
from decimal import Decimal
from typing import Dict, Tuple
import time
from app_market.models.exchange import Exchange
from app_market.prices.publisher import publish_l1_code  # как у тебя

MEXC_BASE = "https://api.mexc.com"
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
    /api/v3/exchangeInfo → {symbol: (BASE, QUOTE)} для включённых рынков.
    У MEXC статус: "1" = online, "2" = pause, "3" = offline.
    Мы принимаем либо status=="1", либо пустой статус (на всякий случай).
    """
    r = requests.get(f"{MEXC_BASE}/api/v3/exchangeInfo", timeout=(4, 10))
    r.raise_for_status()
    d = r.json()

    # у MEXC это обычно "symbols": [...]; на всякий случай проверим fallback "data"
    symbols = d.get("symbols") or d.get("data") or []
    out: Dict[str, Tuple[str, str]] = {}

    for it in symbols:
        if not isinstance(it, dict):
            continue
        sym = (it.get("symbol") or "").upper()
        base = (it.get("baseAsset") or "").upper()
        quote = (it.get("quoteAsset") or "").upper()
        status = (it.get("status") or "").strip()  # "1"/"2"/"3" или пусто

        # пропускаем только явные offline/pause
        if status and status not in ("1", "ONLINE", "TRADING"):  # ONLINE/TRADING на случай неожиданных форматов
            continue

        if sym and base and quote:
            out[sym] = (base, quote)

    return out


def _book_tickers() -> Dict[str, dict]:
    """
    /api/v3/ticker/bookTicker → лучший bid/ask по всем символам.
    Возвращаем {symbol: {...}}.
    """
    r = requests.get(f"{MEXC_BASE}/api/v3/ticker/bookTicker", timeout=(4, 10))
    r.raise_for_status()
    arr = r.json()
    if isinstance(arr, dict):
        arr = [arr]
    return {(it.get("symbol") or "").upper(): it for it in arr if it.get("symbol")}


def _last_prices() -> Dict[str, Decimal]:
    """
    /api/v3/ticker/price → last price по всем символам.
    Возвращаем {symbol: Decimal(lastPrice)}.
    """
    r = requests.get(f"{MEXC_BASE}/api/v3/ticker/price", timeout=(4, 10))
    r.raise_for_status()
    arr = r.json()
    if isinstance(arr, dict):
        arr = [arr]
    out: Dict[str, Decimal] = {}
    for it in arr:
        sym = (it.get("symbol") or "").upper()
        price = it.get("price")
        if sym and price is not None:
            try:
                out[sym] = Decimal(price)
            except Exception:
                pass
    return out


def _server_time_ms() -> int | None:
    """ /api/v3/time → serverTime (мс). Если не удаётся — вернём None. """
    try:
        r = requests.get(f"{MEXC_BASE}/api/v3/time", timeout=(3, 7))
        r.raise_for_status()
        d = r.json()
        st = d.get("serverTime")
        return int(st) if st is not None else None
    except Exception:
        return None


def collect_spot(ex: Exchange, dry_run: bool = False) -> tuple[int, int]:
    """
    Собрать ВСЕ спот-тикеры MEXC и опубликовать L1 «по кодам» (BASE/QUOTE) в Redis.
    Возвращает (pushed, skipped).
    """
    sym_map = _symbols_spot_cached()  # symbol -> (BASE, QUOTE)
    books = _book_tickers()  # symbol -> { bidPrice, askPrice }
    last_map = _last_prices()  # symbol -> Decimal(lastPrice)
    ts_ms = _server_time_ms()  # общий серверный timestamp для консистентности

    pushed = skipped = 0
    exchange_kind = (ex.exchange_kind or "CEX")

    for sym, bk in books.items():
        bq = sym_map.get(sym)
        if not bq:
            skipped += 1
            continue

        base, quote = bq
        try:
            bid = Decimal(bk["bidPrice"])
            ask = Decimal(bk["askPrice"])
            last = last_map.get(sym)
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
                src_symbol=sym,  # напр. BTCUSDT
                extras={"mexc_v": "v3"},
            )
        pushed += 1

    return pushed, skipped
