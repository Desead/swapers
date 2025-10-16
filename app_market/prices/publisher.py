from __future__ import annotations
import json
import time
from decimal import Decimal
from typing import Any, Dict, Optional

import redis
from django.conf import settings


_redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """Ленивая инициализация клиента Redis, decode_responses=True для удобства XADD."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.PRICES_REDIS_URL, decode_responses=True)
    return _redis_client


def _ttl_for_kind(exchange_kind: str) -> int:
    """
    TTL берём из settings.PRICES_TTL_SECONDS по ключу вида 'CEX'/'DEX'/...
    Если ключа нет — дефолт 60.
    """
    table = getattr(settings, "PRICES_TTL_SECONDS", {}) or {}
    return int(table.get(exchange_kind or "CEX", table.get("CEX", 60)))


def publish_l1_code(
    *,
    provider_id: int,
    exchange_kind: str,           # "CEX" | "DEX" | "PSP" | ...
    base_code: str,
    quote_code: str,
    bid: Decimal | str,
    ask: Decimal | str,
    last: Decimal | str | None = None,
    ts_src_ms: int | None = None,
    src_symbol: str = "",
    extras: Dict[str, Any] | None = None,
) -> str:
    """
    Публикация L1 по КОДАМ пары (без каких-либо FK/маппинга):
      1) горячий ключ с TTL: settings.PRICES_L1C_KEY_FMT
      2) событие в Stream:   settings.PRICES_L1C_STREAM
    """
    r = get_redis()
    stream = getattr(settings, "PRICES_L1C_STREAM", "prices:l1c:updates")
    key_fmt = getattr(settings, "PRICES_L1C_KEY_FMT", "price:l1c:{provider}:{base}:{quote}")

    now_ms = int(time.time() * 1000)
    base = (base_code or "").upper()
    quote = (quote_code or "").upper()

    payload = {
        "provider_id": str(provider_id),
        "exchange_kind": exchange_kind,
        "base_code": base,
        "quote_code": quote,
        "bid": str(bid),
        "ask": str(ask),
        "last": "" if last is None else str(last),
        "ts_src_ms": str(ts_src_ms or now_ms),
        "ts_ingest_ms": str(now_ms),
        "status": "OK",
        "latency_ms": "0",
        "src_symbol": src_symbol or f"{base}{quote}",
        "extras": json.dumps(extras or {}),
    }

    key = key_fmt.format(provider=provider_id, base=base, quote=quote)
    r.setex(key, _ttl_for_kind(exchange_kind), json.dumps(payload, separators=(",", ":")))
    ev_id = r.xadd(stream, payload, id="*", maxlen=10_000_000, approximate=True)
    return str(ev_id)
