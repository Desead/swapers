from __future__ import annotations
from django.core.management.base import BaseCommand
from app_market.models.prices.conf import PRICES_L1_STREAM, PRICES_L1_CONSUMER_GROUP
from app_market.models.prices.streaming import get_redis

class Command(BaseCommand):
    help = "Создать (идемпотентно) consumer-group для стрима L1-цен."

    def handle(self, *args, **options):
        r = get_redis()
        try:
            r.xgroup_create(PRICES_L1_STREAM, PRICES_L1_CONSUMER_GROUP, id="0-0", mkstream=True)
            self.stdout.write(self.style.SUCCESS(f"Group '{PRICES_L1_CONSUMER_GROUP}' for stream '{PRICES_L1_STREAM}' created."))
        except Exception:
            self.stdout.write(self.style.WARNING("Group already exists or stream created earlier."))
