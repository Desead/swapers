from __future__ import annotations
import requests
from decimal import Decimal
from typing import Dict, Tuple
import time
from app_market.models.exchange import Exchange
from app_market.prices.publisher import publish_l1_code

_HTX_BASES = (
    "https://api.htx.com",
    "https://api.huobi.pro",
)
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
def _get_json(path: str, *, params=None, timeout=(4, 10)) -> dict:
    last_err = None
    for base in _HTX_BASES:
        try:
            r = requests.get(f"{base}{path}", params=params or {}, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return {}


def _symbols_spot() -> Dict[str, Tuple[str, str]]:
    """
    /v1/common/symbols → список инструментов.
    Возвращаем { symbol(lowercase без разделителя): (BASE, QUOTE) }.
    Фильтруем по state: online/operating.
    """
    d = _get_json("/v1/common/symbols")
    items = (d.get("data") or []) if isinstance(d, dict) else []
    out: Dict[str, Tuple[str, str]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        state = (it.get("state") or "").lower()  # online / offline / suspend / operating
        if state not in ("online", "operating"):
            continue
        sym = (it.get("symbol") or "").lower()  # btcusdt
        b = (it.get("base-currency") or "").upper()
        q = (it.get("quote-currency") or "").upper()
        if sym and b and q:
            out[sym] = (b, q)
    return out


def _tickers_all() -> Dict[str, dict]:
    """
    /market/tickers → все тикеры (best bid/ask/last) одним запросом.
    Возвращаем { symbol(lowercase): {bid, ask, close, _ts_ms} }.
    """
    d = _get_json("/market/tickers")
    if not isinstance(d, dict):
        return {}
    ts_ms = int(d.get("ts") or 0) or None
    arr = d.get("data") or []
    out: Dict[str, dict] = {}
    for it in arr:
        sym = (it.get("symbol") or "").lower()
        if not sym:
            continue
        it["_ts_ms"] = ts_ms
        out[sym] = it
    return out


def collect_spot(ex: Exchange, dry_run: bool = False) -> tuple[int, int]:
    """
    Собрать ВСЕ спот-тикеры HTX и опубликовать L1 «по кодам» (BASE/QUOTE) в Redis.
    Возвращает (pushed, skipped).
    """
    sym_map = _symbols_spot_cached()  # btcusdt -> (BTC, USDT)
    ticks = _tickers_all()  # btcusdt -> { bid, ask, close, _ts_ms }

    pushed = skipped = 0
    exchange_kind = (ex.exchange_kind or "CEX")

    for sym_lc, t in ticks.items():
        bq = sym_map.get(sym_lc)
        if not bq:
            skipped += 1
            continue

        base, quote = bq
        try:
            # HTX: bid/ask/close могут приходить как числа или строки
            bid = Decimal(str(t.get("bid")))
            ask = Decimal(str(t.get("ask")))
            last = Decimal(str(t.get("close"))) if t.get("close") not in (None, "") else None
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
                src_symbol=sym_lc.upper(),  # BTCUSDT
                extras={"htx_v": "v1"},
            )
        pushed += 1

    return pushed, skipped
