from __future__ import annotations
import json
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone as dt_tz
from typing import Dict, Tuple

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from app_market.models.prices.conf import PRICES_L1_STREAM, PRICES_L1_CONSUMER_GROUP
from app_market.models.prices.streaming import get_redis
from app_market.models.prices.price import PriceL1, PriceStatus, VenueType

# Кэш "последней сохраненной точки" на время запуска команды:
_last_saved: Dict[Tuple[int,int,int], Tuple[datetime, Decimal]] = {}

def _mid(bid: Decimal, ask: Decimal) -> Decimal | None:
    try:
        if bid is None or ask is None:
            return None
        m = (bid + ask) / Decimal(2)
        return m if m > 0 else None
    except InvalidOperation:
        return None

class Command(BaseCommand):
    help = "Прочитать пачку событий L1 из Redis Stream и записать значимые точки в БД PriceL1."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=200, help="Сколько сообщений читать за проход")
        parser.add_argument("--block-ms", type=int, default=2000, help="Block read (ms)")
        parser.add_argument("--min-interval-sec", type=int, default=15, help="Мин. интервал между точками для одной пары/ПЛ")
        parser.add_argument("--min-delta-pct", type=float, default=0.30, help="Мин. дельта mid в % для внеплановой записи")
        parser.add_argument("--once", action="store_true", help="Сделать один проход и выйти (по умолчанию да)")

    def handle(self, *args, **opts):
        r = get_redis()
        # Создаём группу (идемпотентно)
        try:
            r.xgroup_create(PRICES_L1_STREAM, PRICES_L1_CONSUMER_GROUP, id="0-0", mkstream=True)
        except Exception:
            pass

        consumer = f"sampler-mgmt"
        batch = int(opts["batch"])
        block_ms = int(opts["block_ms"])
        min_interval = int(opts["min_interval_sec"])
        min_delta_pct = Decimal(str(opts["min_delta_pct"]))

        processed = 0

        while True:
            resp = r.xreadgroup(PRICES_L1_CONSUMER_GROUP, consumer, {PRICES_L1_STREAM: ">"}, count=batch, block=block_ms)
            if not resp:
                break

            _, messages = resp[0]
            for msg_id, fields in messages:
                try:
                    data = {k: v for k, v in fields.items()}  # decode_responses=True → str
                    provider_id = int(data["provider_id"]); base_id = int(data["base_id"]); quote_id = int(data["quote_id"])
                    venue = data.get("venue_type", "CEX")
                    bid = Decimal(data["bid"]); ask = Decimal(data["ask"])
                    last_str = data.get("last") or ""; last = Decimal(last_str) if last_str else None
                    fee_taker_bps = int(data.get("fee_taker_bps","0") or "0")
                    fee_maker_bps = int(data.get("fee_maker_bps","0") or "0")
                    ts_src_ms = int(data.get("ts_src_ms")); ts_ingest_ms = int(data.get("ts_ingest_ms"))
                    seq_str = data.get("seq") or ""; seq = int(seq_str) if seq_str else None
                    status = data.get("status", "OK")
                    latency_ms = int(data.get("latency_ms","0") or "0")
                    src_symbol = data.get("src_symbol",""); src_base_code = data.get("src_base_code",""); src_quote_code = data.get("src_quote_code","")
                    extras = json.loads(data.get("extras") or "{}")

                    ts_src = datetime.fromtimestamp(ts_src_ms/1000.0, tz=dt_tz.utc)
                    ts_ingest = datetime.fromtimestamp(ts_ingest_ms/1000.0, tz=dt_tz.utc)

                    m = _mid(bid, ask)
                    if m is None:
                        r.xack(PRICES_L1_STREAM, PRICES_L1_CONSUMER_GROUP, msg_id)
                        continue

                    key = (provider_id, base_id, quote_id)
                    prev = _last_saved.get(key) or self._load_prev_from_db(key)
                    should_write = False
                    if not prev:
                        should_write = True
                    else:
                        prev_ts, prev_mid = prev
                        if (ts_src - prev_ts).total_seconds() >= min_interval:
                            should_write = True
                        elif prev_mid and prev_mid > 0:
                            delta_pct = abs(m - prev_mid) / prev_mid * Decimal(100)
                            if delta_pct >= min_delta_pct:
                                should_write = True

                    if should_write:
                        with transaction.atomic():
                            obj = PriceL1.objects.create(
                                provider_id=provider_id,
                                venue_type=venue if venue in VenueType.values else VenueType.CEX,
                                base_asset_id=base_id,
                                quote_asset_id=quote_id,
                                src_symbol=src_symbol,
                                src_base_code=src_base_code,
                                src_quote_code=src_quote_code,
                                bid=bid, ask=ask, last=last,
                                fee_taker_bps=fee_taker_bps, fee_maker_bps=fee_maker_bps,
                                ts_src=ts_src, ts_ingest=ts_ingest,
                                seq=seq, latency_ms=latency_ms,
                                status=status if status in PriceStatus.values else PriceStatus.OK,
                                extras=extras,
                            )
                        _last_saved[key] = (obj.ts_src, m)
                        processed += 1

                finally:
                    try:
                        r.xack(PRICES_L1_STREAM, PRICES_L1_CONSUMER_GROUP, msg_id)
                    except Exception:
                        pass

            break  # один проход

        self.stdout.write(self.style.SUCCESS(f"Processed: {processed} messages"))

    def _load_prev_from_db(self, key: Tuple[int,int,int]):
        provider_id, base_id, quote_id = key
        last = (PriceL1.objects
                .filter(provider_id=provider_id, base_asset_id=base_id, quote_asset_id=quote_id)
                .order_by("-ts_src")
                .only("ts_src","bid","ask")
                .first())
        if not last:
            return None
        m = (last.bid + last.ask) / 2 if last.bid and last.ask else None
        return (last.ts_src, m) if m else None
