from django.db import models
from django.utils.translation import gettext_lazy as _t
from .exchange import Exchange

# Используем django-encrypted-model-fields (FIELD_ENCRYPTION_KEY в настройках)
try:
    from encrypted_model_fields.fields import EncryptedCharField
except Exception:  # fall back, чтобы не ронять миграции, если пакет ещё не установлен
    # На этапе разработки можно временно заменить на обычный CharField,
    # но в проде ОБЯЗАТЕЛЬНО поставить пакет и включить шифрование.
    EncryptedCharField = models.CharField  # type: ignore


class ExchangeApiKey(models.Model):
    """
    Набор API-ключей для биржи. Поля опциональны (для чтения котировок иногда не нужны).
    Делаем отдельной моделью, чтобы:
      - поддерживать несколько наборов ключей на одну биржу (label/метка),
      - хранить безопасно и независимо от остальной карточки биржи.
    """
    exchange = models.ForeignKey(
        Exchange,
        on_delete=models.CASCADE,
        related_name="api_keys",
        verbose_name=_t("Биржа"),
    )
    label = models.CharField(
        max_length=64,
        default="default",
        verbose_name=_t("Метка ключей"),
        help_text=_t("Например: main, trading, withdraw-only и т.п."),
    )

    # 4) До трёх полей, все НЕобязательные; шифрованные
    api_key = EncryptedCharField(
        max_length=256, blank=True, null=True,
        verbose_name=_t("API Key"),
    )
    api_secret = EncryptedCharField(
        max_length=256, blank=True, null=True,
        verbose_name=_t("API Secret"),
    )
    api_passphrase = EncryptedCharField(
        max_length=256, blank=True, null=True,
        verbose_name=_t("API Passphrase"),
        help_text=_t("Иногда требуется (например, на некоторых биржах)."),
    )

    is_enabled = models.BooleanField(
        default=True,
        verbose_name=_t("Включён"),
    )

    class Meta:
        verbose_name = _t("API ключи биржи")
        verbose_name_plural = _t("API ключи бирж")
        constraints = [
            models.UniqueConstraint(
                fields=["exchange", "label"],
                name="uniq_exchange_apikey_label",
            )
        ]

    def __str__(self) -> str:
        return f"{self.exchange.name} · {self.label}"
