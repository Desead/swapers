from __future__ import annotations
import json
from datetime import datetime, timezone as dt_tz
from decimal import Decimal, InvalidOperation
from typing import Dict, Tuple

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from django_redis import get_redis_connection

from app_market.models.prices.price import PriceL1, PriceStatus, VenueType  # ваши пути
from app_market.models.exchange import Exchange                      # FK для venue_type по провайдеру при желании
from app_market.models.exchange_asset import ExchangeAsset            # FK на активы
from app_market.models.prices.conf import (
    PRICES_REDIS_ALIAS, PRICES_L1_STREAM, PRICES_L1_CONSUMER_GROUP,
    SAMPLE_DELTA_BY_VENUE, SAMPLE_INTERVAL_SEC_BY_VENUE,
)

# Простой кеш последних сохранённых точек: {(prov, base, quote): (ts_src, mid)}
_last_saved: Dict[Tuple[int, int, int], Tuple[datetime, Decimal]] = {}

def _mid(bid: Decimal, ask: Decimal) -> Decimal | None:
    try:
        if bid is None or ask is None:
            return None
        m = (bid + ask) / Decimal(2)
        return m if m > 0 else None
    except InvalidOperation:
        return None

def _should_sample(venue: str, key: Tuple[int, int, int], ts_src: datetime, mid_val: Decimal) -> bool:
    """
    Решение: писать ли точку в БД (по интервалу и по дельте относительно последней сохранённой).
    """
    delta_pct = Decimal(str(SAMPLE_DELTA_BY_VENUE.get(venue, 0.5)))
    min_interval = SAMPLE_INTERVAL_SEC_BY_VENUE.get(venue, 60)

    prev = _last_saved.get(key)
    if not prev:
        return True
    prev_ts, prev_mid = prev
    if (ts_src - prev_ts).total_seconds() < min_interval:
        # Интервал ещё не прошёл; допускаем запись, если дельта большая
        if prev_mid and mid_val and prev_mid > 0:
            d = abs(mid_val - prev_mid) / prev_mid * Decimal(100)
            return d >= delta_pct
        return False
    # Интервал прошёл — можно писать (или тоже смотреть на дельту, если хотите)
    return True

def _parse_event(raw: Dict[bytes, bytes]) -> Dict[str, str]:
    return {k.decode(): v.decode() for k, v in raw.items()}

@shared_task(bind=True, ignore_result=True, max_retries=0)
def prices_sampler(self, batch: int = 200, block_ms: int = 5000) -> int:
    """
    Читает Redis Stream 'prices:l1:updates' (consumer-group 'sampler'),
    выбирает значимые точки и пишет в БД PriceL1.
    Возвращает количество обработанных сообщений (для логов/метрик).
    """
    r = get_redis_connection(PRICES_REDIS_ALIAS)
    # Инициализация группы (идемпотентно)
    try:
        r.xgroup_create(PRICES_L1_STREAM, PRICES_L1_CONSUMER_GROUP, id="0-0", mkstream=True)
    except Exception:
        pass  # уже создана

    consumer_name = f"sampler-{self.request.hostname or 'worker'}"
    processed = 0

    while True:
        resp = r.xreadgroup(PRICES_L1_CONSUMER_GROUP, consumer_name, {PRICES_L1_STREAM: ">"}, count=batch, block=block_ms)
        if not resp:
            break  # нет данных сейчас

        _, messages = resp[0]
        for msg_id, fields in messages:
            try:
                data = _parse_event(fields)
                provider_id = int(data["provider_id"])
                base_id = int(data["base_id"])
                quote_id = int(data["quote_id"])
                venue = data.get("venue_type", "CEX")
                bid = Decimal(data["bid"])
                ask = Decimal(data["ask"])
                last_str = data.get("last") or ""
                last = Decimal(last_str) if last_str else None
                fee_taker_bps = int(data.get("fee_taker_bps", "0") or "0")
                fee_maker_bps = int(data.get("fee_maker_bps", "0") or "0")
                ts_src_ms = int(data.get("ts_src_ms"))
                ts_ingest_ms = int(data.get("ts_ingest_ms"))
                seq_str = data.get("seq") or ""
                seq = int(seq_str) if seq_str else None
                status = data.get("status", "OK")
                latency_ms = int(data.get("latency_ms", "0") or "0")
                extras = json.loads(data.get("extras") or "{}")
                src_symbol = data.get("src_symbol", "")
                src_base_code = data.get("src_base_code", "")
                src_quote_code = data.get("src_quote_code", "")

                ts_src = datetime.fromtimestamp(ts_src_ms / 1000.0, tz=dt_tz.utc)
                ts_ingest = datetime.fromtimestamp(ts_ingest_ms / 1000.0, tz=dt_tz.utc)

                mid_val = _mid(bid, ask)
                if mid_val is None:
                    r.xack(PRICES_L1_STREAM, PRICES_L1_CONSUMER_GROUP, msg_id)
                    continue

                key = (provider_id, base_id, quote_id)
                if not _should_sample(venue, key, ts_src, mid_val):
                    r.xack(PRICES_L1_STREAM, PRICES_L1_CONSUMER_GROUP, msg_id)
                    continue

                with transaction.atomic():
                    obj = PriceL1.objects.create(
                        provider_id=provider_id,
                        venue_type=venue if venue in VenueType.values else VenueType.CEX,
                        base_asset_id=base_id,
                        quote_asset_id=quote_id,
                        src_symbol=src_symbol,
                        src_base_code=src_base_code,
                        src_quote_code=src_quote_code,
                        bid=bid,
                        ask=ask,
                        last=last,
                        fee_taker_bps=fee_taker_bps,
                        fee_maker_bps=fee_maker_bps,
                        ts_src=ts_src,
                        ts_ingest=ts_ingest,
                        seq=seq,
                        latency_ms=latency_ms,
                        status=status if status in PriceStatus.values else PriceStatus.OK,
                        extras=extras,
                    )
                _last_saved[key] = (obj.ts_src, mid_val)
                processed += 1
            except Exception:
                # Не ACK'аем — сообщение останется в pending у группы для последующей диагностики/ретрая
                continue
            finally:
                try:
                    r.xack(PRICES_L1_STREAM, PRICES_L1_CONSUMER_GROUP, msg_id)
                except Exception:
                    pass

        # Одно «прохождение» — выходим (таску можно вызывать периодически или запустить отдельным воркером)
        break

    return processed
