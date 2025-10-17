from __future__ import annotations
import requests
from decimal import Decimal
from typing import Optional

from app_market.models.exchange import Exchange
from app_market.prices.publisher import publish_l1_code

API_BASE = "https://api.rapira.net"
RATES_URL = f"{API_BASE}/open/market/rates"


def _split_symbol(sym: str) -> tuple[Optional[str], Optional[str]]:
    """
    Символ может быть 'BTC/USDT', 'BTC_USDT' или 'BTC-USDT'.
    Если без разделителя — пробуем типовые котируемые.
    """
    s = (sym or "").strip()
    if not s:
        return None, None
    for sep in ("/", "_", "-"):
        if sep in s:
            b, q = s.split(sep, 1)
            return (b or "").upper(), (q or "").upper()
    su = s.upper()
    for q in ("USDT", "USDC", "BTC", "ETH", "RUB", "USD", "EUR", "UAH"):
        if su.endswith(q) and len(su) > len(q):
            return su[:-len(q)], q
    return None, None


def collect_spot(ex: Exchange, dry_run: bool = False) -> tuple[int, int]:
    """
    Тянем ВСЕ котировки Rapira публичным запросом:
      GET https://api.rapira.net/open/market/rates
    Ожидаемые поля: symbol, bidPrice, askPrice, close (опц.), fee (опц.).
    """
    resp = requests.get(RATES_URL, headers={"Accept": "application/json"}, timeout=(5, 15))
    resp.raise_for_status()
    data = resp.json()
    items = data.get("data") if isinstance(data, dict) else []
    if not isinstance(items, list):
        items = []

    exchange_kind = (ex.exchange_kind or "CEX")
    pushed = skipped = 0

    for row in items:
        if not isinstance(row, dict):
            skipped += 1
            continue

        sym = (row.get("symbol") or "").upper()
        base, quote = _split_symbol(sym)
        if not base or not quote:
            skipped += 1
            continue

        try:
            bid = Decimal(str(row.get("bidPrice")))
            ask = Decimal(str(row.get("askPrice")))
            last = Decimal(str(row.get("close"))) if row.get("close") not in (None, "") else None
        except Exception:
            skipped += 1
            continue

        if bid <= 0 or ask <= 0:
            skipped += 1
            continue

        # fee (доля, например 0.0015 = 15 bps) — кладём как справочную в extras
        fee_bps = 0
        try:
            f = row.get("fee")
            if f is not None:
                fee_bps = int(Decimal(str(f)) * Decimal(10000))
        except Exception:
            fee_bps = 0

        if not dry_run:
            publish_l1_code(
                provider_id=ex.id,
                exchange_kind=exchange_kind,
                base_code=base,
                quote_code=quote,
                bid=bid,
                ask=ask,
                last=last,
                ts_src_ms=None,   # у /open/market/rates общего ts нет — publisher подставит now
                src_symbol=sym,   # например: BTC/USDT
                extras={**({"fee_default_bps": fee_bps} if fee_bps else {}), "rapira_v": "open.market.rates"},
            )
        pushed += 1

    return pushed, skipped
