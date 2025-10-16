from __future__ import annotations
import random
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError

from app_market.models.prices.streaming import publish_l1_update

class Command(BaseCommand):
    help = "Положить тестовую L1-котировку в Redis (горячий ключ + Stream), чтобы проверить контур."

    def add_arguments(self, parser):
        parser.add_argument("--provider-id", type=int, required=True)
        parser.add_argument("--base-id", type=int, required=True)
        parser.add_argument("--quote-id", type=int, required=True)
        parser.add_argument("--venue", default="CEX", choices=["CEX","DEX","PSP","OTC","MANUAL"])
        parser.add_argument("--mid", type=str, default="100.0", help="Центр цены (mid).")
        parser.add_argument("--spread-bps", type=int, default=20, help="Спрэд в б.п. (1/10000). По умолчанию 20 bps = 0.20%.")
        parser.add_argument("--last", type=str, default="")
        parser.add_argument("--symbol", type=str, default="")
        parser.add_argument("--base-code", type=str, default="")
        parser.add_argument("--quote-code", type=str, default="")

    def handle(self, *args, **opts):
        provider_id = opts["provider_id"]
        base_id = opts["base_id"]
        quote_id = opts["quote_id"]
        venue = opts["venue"]
        mid = Decimal(opts["mid"])
        spread_bps = int(opts["spread_bps"])

        # bid/ask вокруг mid
        half = (Decimal(spread_bps) / Decimal(10000)) * mid / 2
        bid = mid - half
        ask = mid + half

        last = opts["last"] or str(mid + Decimal(random.uniform(-0.1, 0.1)))
        symbol = opts["symbol"] or ""
        base_code = opts["base_code"] or ""
        quote_code = opts["quote_code"] or ""

        ev_id = publish_l1_update(
            provider_id=provider_id,
            base_id=base_id,
            quote_id=quote_id,
            venue_type=venue,
            bid=str(bid),
            ask=str(ask),
            last=last,
            src_symbol=symbol,
            src_base_code=base_code,
            src_quote_code=quote_code,
            extras={"demo": True},
        )
        self.stdout.write(self.style.SUCCESS(f"Published demo L1 event id={ev_id}, bid={bid}, ask={ask}"))
