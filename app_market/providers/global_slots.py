from __future__ import annotations

import random
import uuid
import time
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.core.cache import cache


def _max_concurrent() -> int:
    try:
        return int(getattr(settings, "PROVIDER_SYNC_GLOBAL_MAX_CONCURRENT", 0))
    except Exception:
        return 0


def _slot_ttl() -> int:
    try:
        lock_ttl = int(getattr(settings, "PROVIDER_SYNC_LOCK_TTL_SECONDS", 1800))
        return int(getattr(settings, "PROVIDER_SYNC_GLOBAL_SLOT_TTL_SECONDS", lock_ttl))
    except Exception:
        return 1800


@dataclass(frozen=True)
class Slot:
    key: str
    run_id: str


def acquire_global_slot(*, jitter: bool = True) -> Optional[Slot]:
    """
    Пытаемся занять один из N слотов: sync:gslot:{i}.
    Возвращаем Slot при успехе, иначе None (без ожидания).
    """
    n = _max_concurrent()
    if n <= 0:
        return None  # глобальный лимит отключён

    indices = list(range(n))
    if jitter:
        random.shuffle(indices)

    ttl = _slot_ttl()
    run_id = str(uuid.uuid4())
    for i in indices:
        key = f"sync:gslot:{i}"
        if cache.add(key, run_id, timeout=ttl):  # атомарно
            return Slot(key=key, run_id=run_id)
    return None


def acquire_global_slot_blocking(max_wait_seconds: int) -> Optional[Slot]:
    """
    Блокирующая версия: ждём свободный слот до max_wait_seconds, с небольшим экспоненциальным бэк-оффом.
    Возвращаем Slot или None, если не дождались.
    """
    n = _max_concurrent()
    if n <= 0:
        return None  # лимит выключен

    deadline = time.monotonic() + max(0, int(max_wait_seconds))
    attempt = 0
    while True:
        s = acquire_global_slot(jitter=True)
        if s is not None:
            return s
        if time.monotonic() >= deadline:
            return None
        # backoff: 0.25, 0.5, 1.0, 2.0 (cap)
        base = min(0.25 * (2 ** attempt), 2.0)
        time.sleep(base + random.uniform(0.0, 0.2))
        attempt = min(attempt + 1, 3)


def release_global_slot(slot: Slot) -> None:
    """
    Освобождаем слот, но аккуратно: удаляем только если ключ принадлежит нам.
    """
    try:
        cur = cache.get(slot.key)
        if cur == slot.run_id:
            cache.delete(slot.key)
    except Exception:
        # best-effort
        pass
