from __future__ import annotations
import json
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone as dt_tz
from typing import Dict, Tuple

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from app_market.models.price import PriceL1
from app_market.prices.publisher import get_redis

STREAM = getattr(settings, "PRICES_L1C_STREAM", "prices:l1c:updates")
GROUP  = "prices_l1c_saver"   # имя consumer-group для этого сэмплера
CONSUMER = "saver1"           # имя потребителя (можно запускать несколько с разными именами)

# локальный кэш последнего сохранённого mid по ключу (provider_id, base, quote)
_last_saved: Dict[Tuple[int, str, str], Tuple[datetime, Decimal]] = {}


def _mid(b: Decimal, a: Decimal) -> Decimal | None:
    try:
        return (b + a) / Decimal(2)
    except Exception:
        return None


class Command(BaseCommand):
    help = "Разово прочитать часть событий из Redis-стрима цен и сохранить снимки в PriceL1 (с учётом порогов)."

    def add_arguments(self, p):
        p.add_argument("--batch", type=int, default=500, help="сколько сообщений прочитать за раз")
        p.add_argument("--block-ms", type=int, default=1500, help="ожидание данных в XREADGROUP, мс")
        p.add_argument("--min-interval-sec", type=int,
                       default=getattr(settings, "PRICES_DB_SAMPLE_MIN_INTERVAL_SEC", 30))
        p.add_argument("--min-delta-pct", type=float,
                       default=getattr(settings, "PRICES_DB_SAMPLE_MIN_DELTA_PCT", 0.30))

    def handle(self, *args, **opt):
        r = get_redis()
        # создаём consumer-group идемпотентно
        try:
            r.xgroup_create(STREAM, GROUP, id="0-0", mkstream=True)
        except Exception:
            pass

        batch = int(opt["batch"])
        block_ms = int(opt["block_ms"])
        min_interval = int(opt["min_interval_sec"])
        min_delta_pct = Decimal(str(opt["min_delta_pct"]))

        resp = r.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=batch, block=block_ms)
        if not resp:
            self.stdout.write(self.style.SUCCESS("Processed: 0"))
            return

        processed = 0
        _, messages = resp[0]

        for msg_id, fields in messages:
            try:
                d = dict(fields)  # decode_responses=True в publisher
                prov = int(d["provider_id"])
                base = (d["base_code"] or "").upper()
                quote = (d["quote_code"] or "").upper()
                sym = d.get("src_symbol") or f"{base}{quote}"

                # цены
                bid = Decimal(d["bid"]); ask = Decimal(d["ask"])
                last = Decimal(d["last"]) if d.get("last") else None
                m = _mid(bid, ask)
                if m is None:
                    r.xack(STREAM, GROUP, msg_id)
                    continue

                # время
                ts_src_ms = int(d.get("ts_src_ms") or 0)
                ts_ing_ms = int(d.get("ts_ingest_ms") or 0)
                ts_src = datetime.fromtimestamp((ts_src_ms or ts_ing_ms)/1000.0, tz=dt_tz.utc)
                ts_ing = datetime.fromtimestamp((ts_ing_ms or ts_src_ms)/1000.0, tz=dt_tz.utc)

                # пороги: не чаще N сек ИЛИ при сдвиге mid ≥ X%
                key = (prov, base, quote)
                prev = _last_saved.get(key) or self._load_prev(prov, base, quote)
                write = False
                if not prev:
                    write = True
                else:
                    prev_ts, prev_mid = prev
                    age = (ts_src - prev_ts).total_seconds()
                    if age >= min_interval:
                        write = True
                    elif prev_mid and prev_mid > 0:
                        try:
                            if abs(m - prev_mid) / prev_mid * Decimal(100) >= min_delta_pct:
                                write = True
                        except (InvalidOperation, ZeroDivisionError):
                            pass

                if write:
                    extras = json.loads(d.get("extras") or "{}")
                    fee_taker_bps = int(extras.get("fee_taker_bps", 0) or 0)
                    fee_maker_bps = int(extras.get("fee_maker_bps", 0) or 0)

                    with transaction.atomic():
                        obj = PriceL1.objects.create(
                            provider_id=prov,
                            src_symbol=sym,
                            src_base_code=base,
                            src_quote_code=quote,
                            bid=bid, ask=ask, last=last,
                            ts_src=ts_src, ts_ingest=ts_ing,
                            fee_taker_bps=fee_taker_bps,
                            fee_maker_bps=fee_maker_bps,
                            # fee_source пусть останется UNKNOWN (если надо — поднимем из extras позже)
                            extras=extras,
                        )
                    _last_saved[key] = (obj.ts_src, m)
                    processed += 1
            finally:
                # ACK в любом случае, чтобы не залипало
                try:
                    r.xack(STREAM, GROUP, msg_id)
                except Exception:
                    pass

        self.stdout.write(self.style.SUCCESS(f"Processed: {processed}"))

    def _load_prev(self, prov: int, base: str, quote: str):
        last = (PriceL1.objects
                .filter(provider_id=prov, src_base_code=base, src_quote_code=quote)
                .only("ts_src", "bid", "ask")
                .order_by("-ts_src")
                .first())
        if not last:
            return None
        mid = _mid(last.bid, last.ask)
        return (last.ts_src, mid) if mid is not None else None
