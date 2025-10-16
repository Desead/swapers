from __future__ import annotations
import requests
from decimal import Decimal
from typing import Dict
from app_market.models.exchange import Exchange
from app_market.prices.publisher import publish_l1_code

WB_V1_BASE = "https://whitebit.com/api/v1/public"


def _tickers_all() -> Dict[str, dict]:
    """
    /api/v1/public/tickers
    Пример ответа (сокр.):
    {
      "success": true,
      "result": {
        "BTC_USDT": {"ticker":{"bid":"...","ask":"...","last":"..."}, "at": 1690000000},
        ...
      }
    }
    Возвращаем dict: { "BTC_USDT": {...}, ... }
    """
    r = requests.get(f"{WB_V1_BASE}/tickers", timeout=(4, 10))
    r.raise_for_status()
    d = r.json()
    if not isinstance(d, dict) or not d.get("success") or "result" not in d:
        raise RuntimeError(f"WhiteBIT /tickers unexpected: {d!r}")
    res = d["result"]
    if not isinstance(res, dict):
        raise RuntimeError("WhiteBIT /tickers: 'result' must be dict")
    return res


def collect_spot(ex: Exchange, dry_run: bool = False) -> tuple[int, int]:
    """
    Собрать ВСЕ спот-тикеры WhiteBIT (v1) и опубликовать L1 «по кодам» (BASE/QUOTE) в Redis.
    Возвращает (pushed, skipped).
    """
    data = _tickers_all()
    pushed = skipped = 0
    exchange_kind = (ex.exchange_kind or "CEX")

    for market, payload in data.items():
        # ожидаем формат BASE_QUOTE
        if "_" not in market:
            skipped += 1
            continue
        base, quote = market.split("_", 1)
        t = (payload or {}).get("ticker") or {}
        try:
            bid = Decimal(t["bid"])
            ask = Decimal(t["ask"])
            last = Decimal(t["last"]) if t.get("last") else None
            at_s = int((payload or {}).get("at") or 0)  # seconds
            ts_ms = at_s * 1000 if at_s > 0 else None
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
                src_symbol=market,  # "BTC_USDT"
                extras={"wb_v": "v1"},
            )
        pushed += 1

    return pushed, skipped
