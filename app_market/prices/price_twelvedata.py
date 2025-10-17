from __future__ import annotations
import requests
from decimal import Decimal
from typing import List, Tuple, Optional, Dict

from app_market.models.exchange import Exchange
from app_market.models.account import ExchangeApiKey
from app_market.prices.publisher import publish_l1_code

API_BASE = "https://api.twelvedata.com"
FOREX_PAIRS_URL = f"{API_BASE}/forex_pairs"
QUOTE_URL       = f"{API_BASE}/quote"


def _get_api_key_from_db(ex: Exchange) -> str:
    rec = (ExchangeApiKey.objects
           .filter(exchange=ex, is_enabled=True)
           .order_by("id")
           .only("api_key")
           .first())
    if not rec or not (rec.api_key or "").strip():
        raise RuntimeError(f"{ex}: не найден активный API-ключ Twelve Data в ExchangeApiKey")
    return rec.api_key.strip()


def _list_all_symbols(api_key: str) -> List[str]:
    """Список ВСЕХ forex-пар у TD в формате 'BASE/QUOTE'."""
    r = requests.get(FOREX_PAIRS_URL, params={"apikey": api_key},
                     headers={"Accept": "application/json"}, timeout=(10, 25))
    r.raise_for_status()
    d = r.json()
    arr = d.get("data") if isinstance(d, dict) else d
    if not isinstance(arr, list):
        raise RuntimeError("TwelveData /forex_pairs: неожиданный формат ответа")
    out: List[str] = []
    for it in arr:
        if isinstance(it, dict):
            sym = (it.get("symbol") or "").strip().upper()
            if sym and "/" in sym:
                out.append(sym)
    if not out:
        raise RuntimeError("TwelveData /forex_pairs: пустой список символов")
    return out


def _fetch_quotes_batch(symbols: List[str], api_key: str) -> Dict[str, dict]:
    """
    GET /quote?symbol=A,B,C&apikey=...
    Возвращаем мапу {symbol: row}. Поддерживаем оба формата TD:
      1) {"data":[{"symbol":"EUR/USD", ...}, ...]}
      2) {"EUR/USD": {...}, "USD/RUB": {...}, ...}
    """
    params = {"symbol": ",".join(symbols), "apikey": api_key}
    r = requests.get(QUOTE_URL, params=params, headers={"Accept": "application/json"}, timeout=(10, 25))
    r.raise_for_status()
    raw = r.json()

    # Вариант 1: {"data":[...]}
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        return {
            (row.get("symbol") or "").upper(): row
            for row in raw["data"]
            if isinstance(row, dict) and row.get("symbol")
        }

    # Вариант 2: словарь с ключами-символами
    if isinstance(raw, dict):
        want = {s.upper() for s in symbols}
        return {k.upper(): v for k, v in raw.items() if isinstance(v, dict) and k.upper() in want}

    return {}


def collect_spot(ex: Exchange, dry_run: bool = False) -> Tuple[int, int]:
    """
    Twelve Data (FIAT): берём ВСЕ пары через /forex_pairs и котировки через /quote,
    публикуем L1 в Redis. Если bid/ask отсутствуют, публикуем синтетический BBO (bid=ask=close|price|rate),
    помечая это в extras.
    """
    api_key = _get_api_key_from_db(ex)
    all_syms = _list_all_symbols(api_key)

    exchange_kind = ex.exchange_kind
    pushed = skipped = 0
    CHUNK = 30  # безопасный размер батча для TD

    for i in range(0, len(all_syms), CHUNK):
        chunk = all_syms[i:i + CHUNK]
        rows_by_sym = _fetch_quotes_batch(chunk, api_key)

        for sym in chunk:
            row = rows_by_sym.get(sym.upper())
            if not isinstance(row, dict):
                skipped += 1
                continue

            try:
                base, quote = sym.split("/", 1)
                base, quote = base.strip().upper(), quote.strip().upper()
            except Exception:
                skipped += 1
                continue

            # 1) пробуем настоящий L1
            try:
                bid = row.get("bid")
                ask = row.get("ask")
                last = row.get("close") or row.get("price")
                bid = Decimal(str(bid)) if bid not in (None, "") else None
                ask = Decimal(str(ask)) if ask not in (None, "") else None
                last = Decimal(str(last)) if last not in (None, "") else None
            except Exception:
                skipped += 1
                continue

            extras = {"td_type": row.get("type") or "forex"}

            # 2) если нет bid/ask — аккуратно делаем синтетический BBO из доступного поля
            if bid is None or ask is None or bid <= 0 or ask <= 0:
                # порядок приоритетов: close -> price -> rate
                fallback_val = row.get("close")
                if fallback_val in (None, ""):
                    fallback_val = row.get("price")
                if fallback_val in (None, ""):
                    fallback_val = row.get("rate")

                if fallback_val not in (None, ""):
                    try:
                        px = Decimal(str(fallback_val))
                        if px > 0:
                            bid = ask = px
                            extras.update({"synthetic_bbo": True, "synthetic_from": ("rate" if "rate" in row else ("price" if "price" in row else "close"))})
                        else:
                            skipped += 1
                            continue
                    except Exception:
                        skipped += 1
                        continue
                else:
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
                    ts_src_ms=None,     # TD даёт строковый timestamp; пусть проставится ts_ingest
                    src_symbol=sym,     # "USD/RUB"
                    extras=extras,
                )
            pushed += 1

    return pushed, skipped
