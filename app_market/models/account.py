from django.db import models
from django.utils.translation import gettext_lazy as _t
from .exchange import Exchange
from encrypted_model_fields.fields import EncryptedCharField


def _mask_for_view(value: str) -> str:
    if not value:
        return ""
    s = str(value)
    n = len(s)
    if n >= 6:
        return f"{s[:3]}**********{s[-3:]}"
    if n >= 3:
        return f"{s[:3]}**********"
    return "**********"  # для очень коротких не показываем исходные символы


class ExchangeApiKey(models.Model):
    """
    API-ключи храним зашифрованными (api_key / api_secret / api_passphrase),
    а для отображения в админке используем *_view (маскированные дублёры).
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

    # Зашифрованные поля (редактируемые, но невидимые по значению в админке)
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
        help_text=_t("Иногда требуется на некоторых биржах."),
    )

    # Маскированные дублёры (только для просмотра в админке)
    api_key_view = models.CharField(
        max_length=272, blank=True, default="",
        editable=False,
        verbose_name=_t("API Key (вид)"),
    )
    api_secret_view = models.CharField(
        max_length=272, blank=True, default="",
        editable=False,
        verbose_name=_t("API Secret (вид)"),
    )
    api_passphrase_view = models.CharField(
        max_length=272, blank=True, default="",
        editable=False,
        verbose_name=_t("API Passphrase (вид)"),
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

    def save(self, *args, **kwargs):
        # Пересчитываем маски перед сохранением
        self.api_key_view = _mask_for_view(self.api_key or "")
        self.api_secret_view = _mask_for_view(self.api_secret or "")
        self.api_passphrase_view = _mask_for_view(self.api_passphrase or "")
        super().save(*args, **kwargs)
