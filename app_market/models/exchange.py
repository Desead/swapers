from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _t


class ExchangeKind(models.TextChoices):
    CEX = "CEX", _t("Классическая биржа (CEX)")
    DEX = "DEX", _t("Децентрализованная биржа (DEX)")
    PSP = "PSP", _t("Платёжный провайдер (PSP)")
    MANUAL = "MANUAL", _t("Ручной обмен (возможно в офисе)")


class LiquidityProvider(models.TextChoices):
    KUCOIN = "KUCOIN", "KuCoin"
    WHITEBIT = "WHITEBIT", "WhiteBIT"
    RAPIRA = "RAPIRA", "Rapira"
    MEXC = "MEXC", "MEXC"
    MANUAL = "MANUAL", "Manual"
    PAYPAL = "PAYPAL", "PayPal"
    ADVCASH = "ADVCASH", "Advanced Cash"


class Exchange(models.Model):
    # Фиксированный список провайдеров (одна запись на провайдера)
    provider = models.CharField(
        max_length=20,
        choices=LiquidityProvider.choices,
        unique=True,
        db_index=True,
        verbose_name=_t("Название"),
    )

    # Тип провайдера (авто-подставляется из provider при сохранении)
    exchange_kind = models.CharField(
        max_length=10,
        choices=ExchangeKind.choices,
        default=ExchangeKind.CEX,
        db_index=True,
        verbose_name=_t("Тип"),
        editable=False,
        help_text=_t("Устанавливается автоматически при сохранении"),
    )

    # Авто-статус доступности (обновляется health-check’ом)
    is_available = models.BooleanField(
        default=True,
        editable=False,
        db_index=True,
        verbose_name=_t("Доступен"),
        help_text=_t("Изменяется автоматически (health-check, статусы API)."),
    )

    # Режимы работы
    can_receive = models.BooleanField(default=True, verbose_name=_t("Приём средств"))
    can_send = models.BooleanField(default=True, verbose_name=_t("Отдача средств"))

    # Базовый стейблкоин
    stablecoin = models.CharField(
        max_length=20,
        default="USDT",
        verbose_name=_t("Рабочий стейблкоин"),
        help_text=_t("Стейблкоин для расчётов, например: USDT."),
    )

    # --- Торговые комиссии (%, могут быть отрицательными), теперь симметричные: 12,5 ---
    spot_taker_fee = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0.1"),
        verbose_name=_t("Спот: тейкер, %"),
        help_text=_t("Может быть отрицательной."),
    )
    spot_maker_fee = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0.1"),
        verbose_name=_t("Спот: мейкер, %"),
        help_text=_t("Может быть отрицательной."),
    )
    futures_taker_fee = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0.1"),
        verbose_name=_t("Фьючерсы: тейкер, %"),
        help_text=_t("Может быть отрицательной."),
    )
    futures_maker_fee = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0.1"),
        verbose_name=_t("Фьючерсы: мейкер, %"),
        help_text=_t("Может быть отрицательной."),
    )

    # --- Комиссии на ввод/вывод ---
    # Проценты и фикс допускают 0 (семантика: 0 = не используется). Знак не ограничиваем.
    fee_deposit_percent = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0"),
        verbose_name=_t("Ввод: %"),
    )
    fee_deposit_fixed = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0"),
        verbose_name=_t("Ввод: фикс"),
    )
    # Ограничители комиссии (>= 0), применяются после расчёта % + фикс; 0 = без минимума/максимума
    fee_deposit_min = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Ввод: мин. комиссия"),
    )
    fee_deposit_max = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Ввод: макс. комиссия"),
    )

    fee_withdraw_percent = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0"),
        verbose_name=_t("Вывод: %"),
    )
    fee_withdraw_fixed = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0"),
        verbose_name=_t("Вывод: фикс"),
    )
    fee_withdraw_min = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Вывод: мин. комиссия"),
    )
    fee_withdraw_max = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Вывод: макс. комиссия"),
    )

    # Отображение и вебхук
    show_prices_on_home = models.BooleanField(
        default=False, db_index=True, verbose_name=_t("Цены на главной")
    )
    webhook_endpoint = models.URLField(
        blank=True, default="", verbose_name=_t("Webhook endpoint"),
    )

    class Meta:
        verbose_name = _t("Поставщик ликвидности")
        verbose_name_plural = _t("Поставщики ликвидности")
        ordering = ["provider"]

    def __str__(self) -> str:
        return self.get_provider_display()

    # Валидации/нормализации
    def _auto_kind_from_provider(self) -> str:
        if self.provider in {LiquidityProvider.PAYPAL, LiquidityProvider.ADVCASH}:
            return ExchangeKind.PSP
        if self.provider == LiquidityProvider.MANUAL:
            return ExchangeKind.MANUAL
        return self.exchange_kind  # по умолчанию оставляем как есть

    def clean(self):
        # min <= max (если оба ненулевые). 0 = «без ограничителя».
        if self.fee_deposit_min and self.fee_deposit_max:
            if self.fee_deposit_max < self.fee_deposit_min:
                raise ValidationError({"fee_deposit_max": _t("Максимум не может быть меньше минимума.")})
        if self.fee_withdraw_min and self.fee_withdraw_max:
            if self.fee_withdraw_max < self.fee_withdraw_min:
                raise ValidationError({"fee_withdraw_max": _t("Максимум не может быть меньше минимума.")})

    def save(self, *args, **kwargs):
        # Авто-тип по провайдеру
        mapped_kind = self._auto_kind_from_provider()
        if mapped_kind != self.exchange_kind:
            self.exchange_kind = mapped_kind

        # Нормализация стейблкоина
        if self.stablecoin:
            self.stablecoin = self.stablecoin.strip().upper()

        # Полная валидация
        self.full_clean()
        super().save(*args, **kwargs)
