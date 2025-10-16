from __future__ import annotations
from django.conf import settings

PRICES_L1_KEY_FMT = getattr(settings, "PRICES_L1_KEY_FMT", "price:l1:{provider_id}:{base_id}:{quote_id}")
PRICES_L1_STREAM = getattr(settings, "PRICES_L1_STREAM", "prices:l1:updates")
PRICES_L1_CONSUMER_GROUP = getattr(settings, "PRICES_L1_GROUP", "sampler")

TTL_BY_VENUE = {
    "CEX": 10, "DEX": 90, "PSP": 180, "OTC": 180, "MANUAL": 300,
}
SAMPLE_DELTA_BY_VENUE = {
    "CEX": 0.30, "DEX": 0.50, "PSP": 0.50, "OTC": 0.50, "MANUAL": 0.50,
}
SAMPLE_INTERVAL_SEC_BY_VENUE = {
    "CEX": 15, "DEX": 60, "PSP": 300, "OTC": 300, "MANUAL": 300,
}
