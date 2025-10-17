# app_market/collectors/schedules.py
from __future__ import annotations

from django.conf import settings


def max_parallel_providers() -> int:
    return int(getattr(settings, "COLLECTORS_MAX_PARALLEL_PROVIDERS", 2))


def price_freshness_minutes() -> int:
    return int(getattr(settings, "COLLECTORS_PRICE_FRESHNESS_MINUTES", 10))


def dump_enabled_default() -> bool:
    return bool(getattr(settings, "COLLECTORS_DUMP_ENABLED", False))


def wallet_interval_seconds() -> int:
    return int(getattr(settings, "COLLECTORS_WALLET_INTERVAL_S", 3600))


def prices_interval_seconds() -> int:
    return int(getattr(settings, "COLLECTORS_PRICES_INTERVAL_S", 10))
