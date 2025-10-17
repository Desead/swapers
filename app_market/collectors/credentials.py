from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app_market.models import Exchange, ExchangeApiKey

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CredentialBundle:
    key: Optional[str]
    secret: Optional[str]
    passphrase: Optional[str]
    api_broker: Optional[str]
    role: str = "DATA_READONLY"


def get(provider: str, role: str = "DATA_READONLY") -> Optional[CredentialBundle]:
    """
    Возвращает бандл ключей для указанного провайдера.

    Шаги:
      1) Находим Exchange строго по полю Exchange.provider == provider.
      2) Берём последний включённый ExchangeApiKey (is_enabled=True) для этого Exchange.
      3) Читаем строго поля: api_key, api_secret, api_passphrase, api_broker.

    Если ключи не найдены — возвращаем None (например, для PUBLIC-источников).
    """
    ex = Exchange.objects.filter(provider=provider).order_by("id").first()
    if ex is None:
        log.info("Credentials: Exchange not found for provider=%s", provider)
        return None

    rec = (
        ExchangeApiKey.objects
        .filter(exchange=ex, is_enabled=True)
        .order_by("id")
        .first()
    )
    if rec is None:
        log.info("Credentials: no active ExchangeApiKey for provider=%s (exchange id=%s)", provider, ex.id)
        return None

    # Строгое обращение к полям — если поля нет, это ошибка разработки/миграций.
    bundle = CredentialBundle(
        key=rec.api_key,
        secret=rec.api_secret,
        passphrase=rec.api_passphrase,
        api_broker=rec.api_broker,
        role=role,
    )
    return bundle
