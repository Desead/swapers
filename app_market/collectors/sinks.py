# app_market/collectors/sinks.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable, Optional

from django.apps import apps
from django.conf import settings

from .types import L1PriceDTO, WalletAssetDTO

log = logging.getLogger(__name__)

# --- Redis helpers ---------------------------------------------------------

def _get_redis():
    # Предпочитаем django-redis, иначе прямое подключение
    try:
        from django_redis import get_redis_connection
        return get_redis_connection("default")
    except Exception:
        pass

    try:
        import redis
        url = getattr(settings, "REDIS_URL", "redis://127.0.0.1:6379/0")
        return redis.StrictRedis.from_url(url)
    except Exception as e:
        log.error("Redis not available: %s", e)
        return None


# --- Wallet assets DB sink -------------------------------------------------

class WalletDBSink:
    """
    Идемпотентная запись ассетов кошелька в БД.
    Чтобы не зависеть от конкретной модели, используем dotted-path из настроек:
      settings.COLLECTORS_WALLET_UPSERT_FUNC = "app_market.services.wallet_upsert:upsert_assets"
    Эта функция должна уметь upsert-ить пачку WalletAssetDTO.
    """
    def __init__(self):
        self.dotted = getattr(settings, "COLLECTORS_WALLET_UPSERT_FUNC", None)

    def upsert_many(self, provider: str, items: Iterable[WalletAssetDTO]) -> int:
        if not self.dotted:
            log.warning("WalletDBSink: COLLECTORS_WALLET_UPSERT_FUNC is not configured; skip DB write.")
            return 0

        mod_name, func_name = self.dotted.split(":", 1)
        func = __import__(mod_name, fromlist=[func_name])
        upsert = getattr(func, func_name)
        try:
            result = upsert(provider=provider, items=list(items))  # ожидаемый контракт вашей функции
            return int(result or 0)
        except Exception as e:
            log.exception("WalletDBSink: upsert failed for provider=%s: %s", provider, e)
            return 0


# --- Prices sinks ----------------------------------------------------------

class PricesRedisSink:
    """
    Публикует L1 в Redis (основной путь).
    Ключи/каналы читаем из настроек:
      - settings.COLLECTORS_PRICES_STREAM (например, "prices:l1")
      - settings.COLLECTORS_PRICES_HASH_PREFIX (например, "prices:last")
    """
    def __init__(self):
        self.redis = _get_redis()
        self.stream = getattr(settings, "COLLECTORS_PRICES_STREAM", "prices:l1")
        self.hash_prefix = getattr(settings, "COLLECTORS_PRICES_HASH_PREFIX", "prices:last")

    def push_many(self, provider: str, prices: Iterable[L1PriceDTO]) -> int:
        if not self.redis:
            return 0
        pushed = 0
        pipe = self.redis.pipeline()
        for p in prices:
            key = f"{self.hash_prefix}:{provider}:{p.base}:{p.quote}"
            as_of = (p.ts_price or datetime.utcnow()).isoformat()
            # Храним «последнее значение» в хеше (быстрая выдача фронту/админке)
            pipe.hset(key, mapping={
                "last": p.last,
                "as_of": as_of,
                "provider_symbol": p.provider_symbol or "",
            })
            pipe.expire(key, int(getattr(settings, "COLLECTORS_PRICES_HASH_TTL", 3600)))
            # Ивент в stream (если нужно подписчикам)
            pipe.xadd(self.stream, {
                "provider": provider,
                "base": p.base, "quote": p.quote,
                "last": p.last,
                "as_of": as_of,
            }, maxlen=int(getattr(settings, "COLLECTORS_PRICES_STREAM_MAXLEN", 10000)))
            pushed += 1
        try:
            pipe.execute()
        except Exception as e:
            log.exception("PricesRedisSink: redis pipeline failed: %s", e)
            return 0
        return pushed


class PricesAdminMirror:
    """
    «Зеркало» для админки без истории: одна строка на (provider, base, quote),
    поле as_of для подсветки устаревших значений. Если модели нет — молча пропускаем.
    Ожидаем модель app_market.MarketPriceMirror с полями:
      provider (str), base (str), quote (str), last (Decimal/str), as_of (DateTime), provider_symbol (str)
    """
    def __init__(self, freshness_minutes: Optional[int] = None):
        self.freshness = int(getattr(settings, "COLLECTORS_PRICE_FRESHNESS_MINUTES", 10)
                             if freshness_minutes is None else freshness_minutes)
        try:
            self.Model = apps.get_model("app_market", "MarketPriceMirror")
        except Exception:
            self.Model = None

    def upsert_many(self, provider: str, prices: Iterable[L1PriceDTO]) -> int:
        if not self.Model:
            log.debug("PricesAdminMirror: model app_market.MarketPriceMirror not found; skip DB mirror.")
            return 0

        cnt = 0
        for p in prices:
            as_of = p.ts_price or datetime.utcnow()
            try:
                obj, _ = self.Model.objects.get_or_create(
                    provider=provider, base=p.base, quote=p.quote,
                    defaults={"last": p.last, "as_of": as_of, "provider_symbol": p.provider_symbol or ""},
                )
                if obj.last != p.last or obj.provider_symbol != (p.provider_symbol or ""):
                    obj.last = p.last
                    obj.provider_symbol = p.provider_symbol or ""
                # Обновляем as_of всегда
                obj.as_of = as_of
                obj.save(update_fields=["last", "provider_symbol", "as_of"])
                cnt += 1
            except Exception as e:
                log.exception("PricesAdminMirror: upsert failed for %s/%s-%s: %s", provider, p.base, p.quote, e)
        return cnt

    def is_fresh(self, as_of: datetime) -> bool:
        return datetime.utcnow() - as_of <= timedelta(minutes=self.freshness)


class VoidSink:
    def noop(self, *_args, **_kwargs) -> int:
        return 0
