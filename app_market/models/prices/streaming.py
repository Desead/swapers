from __future__ import annotations
import json
from time import time
from typing import Any, Dict

import redis
from django.conf import settings

from .conf import PRICES_L1_KEY_FMT, PRICES_L1_STREAM, TTL_BY_VENUE

# Ленивая инициализация одного клиента на процесс
_redis_client: redis.Redis | None = None
def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        # decode_responses=True → строки на вход/выход, удобно для XADD
        _redis_client = redis.from_url(settings.PRICES_REDIS_URL, decode_responses=True)
    return _redis_client

def _ttl_for(venue_type: str) -> int:
    return TTL_BY_VENUE.get(venue_type, 60)

def _hot_key(provider_id: int, base_id: int, quote_id: int) -> str:
    return PRICES_L1_KEY_FMT.format(provider_id=provider_id, base_id=base_id, quote_id=quote_id)

def publish_l1_update(
    *,
    provider_id: int,
    base_id: int,
    quote_id: int,
    venue_type: str,
    bid: str,
    ask: str,
    last: str | None = None,
    fee_taker_bps: int = 0,
    fee_maker_bps: int = 0,
    ts_src_ms: int | None = None,
    ts_ingest_ms: int | None = None,
    seq: int | None = None,
    status: str = "OK",
    latency_ms: int = 0,
    src_symbol: str = "",
    src_base_code: str = "",
    src_quote_code: str = "",
    extras: Dict[str, Any] | None = None,
) -> str:
    r = get_redis()
    now_ms = int(time() * 1000)
    ts_ingest_ms = ts_ingest_ms or now_ms

    payload = {
        "provider_id": str(provider_id),
        "base_id": str(base_id),
        "quote_id": str(quote_id),
        "venue_type": venue_type,
        "bid": str(bid),
        "ask": str(ask),
        "last": "" if last is None else str(last),
        "fee_taker_bps": str(fee_taker_bps),
        "fee_maker_bps": str(fee_maker_bps),
        "ts_src_ms": str(ts_src_ms or now_ms),
        "ts_ingest_ms": str(ts_ingest_ms),
        "seq": "" if seq is None else str(seq),
        "status": status,
        "latency_ms": str(latency_ms),
        "src_symbol": src_symbol,
        "src_base_code": src_base_code,
        "src_quote_code": src_quote_code,
        "extras": json.dumps(extras or {}),
    }

    # 1) Горячий ключ (строка JSON) с TTL
    r.setex(_hot_key(provider_id, base_id, quote_id), _ttl_for(venue_type), json.dumps(payload, separators=(",", ":")))

    # 2) Событие в Stream
    event_id = r.xadd(PRICES_L1_STREAM, payload, id="*", maxlen=10_000_000, approximate=True)
    return str(event_id)
