# app_market/collectors/credentials.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from django.apps import apps

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CredentialBundle:
    key: Optional[str] = None
    secret: Optional[str] = None
    passphrase: Optional[str] = None
    subaccount: Optional[str] = None
    extra: Any = None
    role: str = "DATA_READONLY"


def _get_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except Exception as e:
        log.warning("Credentials: cannot load model %s.%s (%s).", app_label, model_name, e)
        return None


def _field_names(model) -> set[str]:
    return {f.name for f in getattr(model, "_meta").get_fields()}


def _find_exchange_by_code(Exchange, provider: str):
    """
    Пытаемся найти Exchange по одному из типичных полей.
    Порядок важен: сначала 'provider' (часто enum/код), дальше code/slug/name/label.
    """
    fields = _field_names(Exchange)
    candidates = ["provider", "code", "slug", "name", "label"]
    for fname in candidates:
        if fname in fields:
            try:
                obj = Exchange.objects.filter(**{f"{fname}__iexact": provider}).first()
                if obj:
                    return obj
            except Exception as e:
                log.debug("Credentials: lookup Exchange by %s failed: %s", fname, e)
    return None


def get(provider: str, role: str = "DATA_READONLY") -> Optional[CredentialBundle]:
    """
    Единая точка получения ключей:
      1) Ищем Exchange по коду/имени (provider/code/slug/name/label — что есть у модели).
      2) Берём последний включённый ExchangeApiKey для этого Exchange.
    Если ничего не нашли — вернём None (PUBLIC-провайдерам ключи не нужны).
    """
    Exchange = _get_model("app_market", "Exchange")
    ExchangeApiKey = _get_model("app_market", "ExchangeApiKey")
    if not Exchange or not ExchangeApiKey:
        return None

    try:
        exch = _find_exchange_by_code(Exchange, provider)
        if not exch:
            log.info("Credentials: Exchange not found for provider=%s", provider)
            return None

        q = ExchangeApiKey.objects.filter(exchange=exch)

        # Включённые ключи: is_enabled или is_active (что есть)
        fields = _field_names(ExchangeApiKey)
        if "is_enabled" in fields:
            q = q.filter(is_enabled=True)
        elif "is_active" in fields:
            q = q.filter(is_active=True)

        obj = q.order_by("-id").first()
        if not obj:
            log.info("Credentials: no active keys for provider=%s (exchange id=%s)", provider, getattr(exch, "id", None))
            return None

        # Мягко читаем имена полей
        key = getattr(obj, "api_key", None) or getattr(obj, "key", None)
        secret = getattr(obj, "api_secret", None) or getattr(obj, "secret", None)
        passphrase = getattr(obj, "api_passphrase", None) or getattr(obj, "passphrase", None)
        subaccount = getattr(obj, "subaccount", None)

        return CredentialBundle(
            key=key,
            secret=secret,
            passphrase=passphrase,
            subaccount=subaccount,
            role=role,
        )
    except Exception as e:
        log.exception("Credentials: failed to read ExchangeApiKey for provider=%s: %s", provider, e)
        return None
