from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Optional
import importlib

from django.conf import settings
import redis

from .types import L1PriceDTO, WalletAssetDTO

log = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────────────────
# Redis (жёстко через redis-py, без django-redis)
# ───────────────────────────────────────────────────────────────────────────────

def _get_redis():
    """
    Прямое подключение по settings.PRICES_REDIS_URL через redis-py.
    Если URL отсутствует — это ошибка конфигурации.
    """
    if not hasattr(settings, "PRICES_REDIS_URL"):
        raise RuntimeError("PRICES_REDIS_URL is not configured in settings")

    url = settings.PRICES_REDIS_URL
    client = redis.StrictRedis.from_url(url)

    # Лёгкая диагностика (не валим процесс на временной сетевой ошибке)
    try:
        client.ping()
    except Exception as ping_err:
        log.error("Redis ping failed at %s: %s", url, ping_err)

    return client


# ───────────────────────────────────────────────────────────────────────────────
# Wallet assets → DB
# ───────────────────────────────────────────────────────────────────────────────

class WalletDBSink:
    """
    Идемпотентный upsert активов кошелька в БД через единую функцию,
    заданную в настройках как dotted-path:
      settings.COLLECTORS_WALLET_UPSERT_FUNC = "app_market.services.wallet_upsert:upsert_assets"
    """
    def __init__(self):
        if not hasattr(settings, "COLLECTORS_WALLET_UPSERT_FUNC"):
            raise RuntimeError("COLLECTORS_WALLET_UPSERT_FUNC is not set in settings")

        dotted = settings.COLLECTORS_WALLET_UPSERT_FUNC  # type: ignore[attr-defined]
        if ":" not in dotted:
            raise ValueError("COLLECTORS_WALLET_UPSERT_FUNC must be 'module.path:func_name'")
        mod_name, func_name = dotted.split(":", 1)

        try:
            mod = importlib.import_module(mod_name)
            self._upsert = getattr(mod, func_name)
        except Exception as e:
            raise RuntimeError(f"Cannot import wallet upsert function '{dotted}': {e}") from e

    def upsert_many(self, provider: str, items: Iterable[WalletAssetDTO]) -> int:
        try:
            return int(self._upsert(provider=provider, items=list(items)))  # ожидаемый контракт
        except Exception as e:
            log.exception("WalletDBSink: upsert failed for provider=%s: %s", provider, e)
            return 0


# ───────────────────────────────────────────────────────────────────────────────
# Prices → Redis (+ stream)
# ───────────────────────────────────────────────────────────────────────────────

class PricesRedisSink:
    """
    Публикация L1 в Redis:
      * Хеш «последних значений» по ключу:  {hash_prefix}:{PROVIDER}:{BASE}:{QUOTE}
      * Стрим событий: settings.COLLECTORS_PRICES_STREAM
    Все ключи читаем жёстко из настроек, кроме MAXLEN — он опциональный.
    """
    def __init__(self):
        self.redis = _get_redis()

        # обязательные настройки
        try:
            self.stream = settings.COLLECTORS_PRICES_STREAM               # type: ignore[attr-defined]
            self.hash_prefix = settings.COLLECTORS_PRICES_HASH_PREFIX     # type: ignore[attr-defined]
            self.hash_ttl = int(settings.COLLECTORS_PRICES_HASH_TTL)      # type: ignore[attr-defined]
        except AttributeError as e:
            raise RuntimeError(f"PricesRedisSink: missing required setting: {e}")

        # опциональная длина стрима
        self.stream_maxlen: Optional[int] = getattr(settings, "COLLECTORS_PRICES_STREAM_MAXLEN", None)

    def push_many(self, provider: str, prices: Iterable[L1PriceDTO]) -> int:
        pipe = self.redis.pipeline()
        pushed = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        for p in prices:
            key = f"{self.hash_prefix}:{provider}:{p.base}:{p.quote}"
            as_of = (p.ts_price or datetime.now(timezone.utc)).isoformat()

            # хеш «последних значений»
            pipe.hset(key, mapping={
                "last": str(p.last) if p.last is not None else "",
                "as_of": as_of,
                "provider_symbol": p.provider_symbol or "",
                "updated_at": now_iso,
            })
            pipe.expire(key, self.hash_ttl)

            # событие в стрим
            fields = {
                "provider": provider,
                "base": p.base,
                "quote": p.quote,
                "last": str(p.last) if p.last is not None else "",
                "as_of": as_of,
            }
            if self.stream_maxlen is not None:
                pipe.xadd(self.stream, fields, maxlen=self.stream_maxlen)
            else:
                pipe.xadd(self.stream, fields)

            pushed += 1

        try:
            pipe.execute()
        except Exception as e:
            log.exception("PricesRedisSink: redis pipeline failed: %s", e)
            return 0

        return pushed
