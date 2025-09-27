from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _t
from .exchange import Exchange, ExchangeKind


class PaymentEnvironment(models.TextChoices):
    LIVE = "LIVE", _t("Прод (LIVE)")
    SANDBOX = "SANDBOX", _t("Песочница (SANDBOX)")


class PaymentProviderProfile(models.Model):
    """
    Профиль платёжного провайдера (PayPal / AdvCash / Skrill и т.п.)
    Привязан 1:1 к Exchange с exchange_kind=PSP.
    Минимальный набор полей v1 — только то, что нужно в ближайшей работе.
    """
    exchange = models.OneToOneField(
        Exchange,
        on_delete=models.CASCADE,
        related_name="psp_profile",
        verbose_name=_t("Провайдер (Exchange)"),
    )

    environment = models.CharField(
        max_length=8,
        choices=PaymentEnvironment.choices,
        default=PaymentEnvironment.LIVE,
        db_index=True,
        verbose_name=_t("Окружение"),
        help_text=_t("LIVE или SANDBOX."),
    )

    # Идентификаторы (часто встречаются у PSP)
    merchant_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_t("Merchant ID"),
    )
    account_email = models.EmailField(
        blank=True,
        default="",
        verbose_name=_t("Учётный email в PSP"),
    )

    # Точки доступа/кабинет (опционально)
    api_base_url = models.URLField(
        blank=True,
        default="",
        verbose_name=_t("API Base URL"),
    )
    dashboard_url = models.URLField(
        blank=True,
        default="",
        verbose_name=_t("URL кабинета"),
    )

    # Валюта расчётов по умолчанию для PSP (обычно фиат), нормализуем в UPPER
    settlement_currency = models.CharField(
        max_length=10,
        default="USD",
        verbose_name=_t("Валюта расчёта"),
        help_text=_t("Например: USD."),
    )

    # Комиссии (v1): проценты и фикс — отдельно для приёма и для выплат
    fee_deposit_percent = models.DecimalField(
        max_digits=7, decimal_places=4, default=Decimal("0"),
        verbose_name=_t("Комиссия на приём, %"),
    )
    fee_deposit_fixed = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"),
        verbose_name=_t("Комиссия на приём, фикс"),
        help_text=_t("В валюте расчёта."),
    )
    fee_payout_percent = models.DecimalField(
        max_digits=7, decimal_places=4, default=Decimal("0"),
        verbose_name=_t("Комиссия на выплату, %"),
    )
    fee_payout_fixed = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"),
        verbose_name=_t("Комиссия на выплату, фикс"),
        help_text=_t("В валюте расчёта."),
    )

    # Простые лимиты (v1) — агрегированные; валютно-специфичные правила добавим позже
    min_deposit = models.DecimalField(
        max_digits=18, decimal_places=6, null=True, blank=True,
        verbose_name=_t("Мин. приём"),
    )
    max_deposit = models.DecimalField(
        max_digits=18, decimal_places=6, null=True, blank=True,
        verbose_name=_t("Макс. приём"),
    )
    min_payout = models.DecimalField(
        max_digits=18, decimal_places=6, null=True, blank=True,
        verbose_name=_t("Мин. выплата"),
    )
    max_payout = models.DecimalField(
        max_digits=18, decimal_places=6, null=True, blank=True,
        verbose_name=_t("Макс. выплата"),
    )

    # Вебхуки/идемпотентность (минимум)
    webhook_endpoint = models.URLField(
        blank=True,
        default="",
        verbose_name=_t("Webhook endpoint"),
    )
    idempotency_window_sec = models.PositiveIntegerField(
        default=300,
        verbose_name=_t("Окно идемпотентности, сек"),
        help_text=_t("Защита от повторной обработки (по умолчанию 5 минут)."),
    )

    class Meta:
        verbose_name = _t("Платёжная система")
        verbose_name_plural = _t("Платёжные системы")

    def __str__(self) -> str:
        return f"{self.exchange.name} · {self.get_environment_display()}"

    # Валидация и нормализация
    def clean(self):
        if self.exchange and self.exchange.exchange_kind != ExchangeKind.PSP:
            raise ValidationError(
                {"exchange": _t("Профиль PSP разрешён только для бирж с типом PSP.")}
            )

    def save(self, *args, **kwargs):
        # Всегда валидируем, чтобы нельзя было записать профиль на non-PSP
        self.full_clean()
        if self.settlement_currency:
            self.settlement_currency = self.settlement_currency.strip().upper()
        super().save(*args, **kwargs)
