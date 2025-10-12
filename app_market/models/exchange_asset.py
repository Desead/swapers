from __future__ import annotations

from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _t

from django.conf import settings

AMOUNT_MAX_DIGITS = settings.DECIMAL_AMOUNT_INT_DIGITS + settings.DECIMAL_AMOUNT_DEC_PLACES
AMOUNT_DEC_PLACES = settings.DECIMAL_AMOUNT_DEC_PLACES

PERCENT_MAX_DIGITS = settings.DECIMAL_PERCENT_MAX_DIGITS
PERCENT_DEC_PLACES = settings.DECIMAL_PERCENT_PLACES_DB


class AssetKind(models.TextChoices):
    """
    Все существующие типы активов
    """
    CRYPTO = "CRYPTO", _t("Крипта")
    FIAT = "FIAT", _t("Фиат")
    PSP_MONEY = "PSP_MONEY", _t("Платёжка")
    CASH = "CASH", _t("Наличные")
    NOTDEFINED = "NOTDEFINED", _t("Не определён")


class ExchangeAsset(models.Model):
    """
    Конкретная позиция у конкретного ПЛ: «монета + сеть/канал».
    Примеры: USDT@TRC20 (KuCoin), BTC@BTC (WhiteBIT), RUB@SBERBANK (Сбер), USD@PAYPAL.
    """

    exchange = models.ForeignKey(
        "app_market.Exchange",
        on_delete=models.CASCADE,
        related_name="assets",
        db_index=True,
        verbose_name=_t("Поставщик"),
    )

    asset_code = models.CharField(
        max_length=32,
        db_index=True,
        verbose_name=_t("Тикет"),
        editable=False,
    )
    asset_name = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_t("Название"),
        editable=False,
    )
    chain_code = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name=_t("Сеть"),
        editable=False,
    )
    chain_name = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_t("Сеть название"),
        editable=False,
    )

    # Ручные флаги (включение/выключение руками оператора)
    D = models.BooleanField(default=True, verbose_name=_t("Ввод (ручной)"))
    W = models.BooleanField(default=True, verbose_name=_t("Вывод (ручной)"))

    # Автоматические флаги (обновляются адаптерами/проверками)
    AD = models.BooleanField(default=True, verbose_name=_t("Ввод (авто)"))
    AW = models.BooleanField(default=True, verbose_name=_t("Вывод (авто)"))

    # Подтверждения
    confirmations_deposit = models.PositiveIntegerField(
        default=0, verbose_name=_t("Подтверждений для ввода")
    )
    confirmations_withdraw = models.PositiveIntegerField(
        default=0, verbose_name=_t("Подтверждений для вывода")
    )

    # Комиссии/лимиты на ВВОД
    deposit_fee_percent = models.DecimalField(
        max_digits=PERCENT_MAX_DIGITS, decimal_places=PERCENT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        verbose_name=_t("Комиссия ввода, %"),
    )
    deposit_fee_fixed = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Комиссия ввода, фикс"),
    )
    deposit_min = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Мин. ввод"),
    )
    deposit_max = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Макс. ввод"),
    )
    # В USDT-эквиваленте (для массовых политик)
    deposit_min_usdt = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("5"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Мин. ввод (в USDT)"),
    )
    deposit_max_usdt = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Макс. ввод (в USDT)"),
    )

    # Комиссии/лимиты на ВЫВОД
    withdraw_fee_percent = models.DecimalField(
        max_digits=PERCENT_MAX_DIGITS, decimal_places=PERCENT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        verbose_name=_t("Комиссия вывода, %"),
    )
    withdraw_fee_fixed = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Комиссия вывода, фикс"),
    )
    withdraw_min = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Мин. вывод"),
    )
    withdraw_max = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Макс. вывод"),
    )
    # В USDT-эквиваленте
    withdraw_min_usdt = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("5"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Мин. вывод (в USDT)"),
    )
    withdraw_max_usdt = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Макс. вывод (в USDT)"),
    )

    # Тип/точность/номинал
    asset_kind = models.CharField(
        max_length=16, choices=AssetKind.choices, default=AssetKind.CRYPTO, db_index=True,
        verbose_name=_t("Тип актива"),
    )
    amount_precision = models.PositiveSmallIntegerField(
        default=8, verbose_name=_t("Точность актива")
    )
    amount_precision_display = models.PositiveSmallIntegerField(
        default=5, verbose_name=_t("Точность на экране")
    )
    nominal = models.PositiveIntegerField(
        default=1, verbose_name=_t("Номинал"),
    )

    # Резервы
    reserve_current = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Текущий резерв"),
    )
    reserve_min = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Мин. резерв"),
    )
    reserve_max = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Макс. резерв"),
    )

    # Доп. атрибуты
    requires_memo = models.BooleanField(default=False, verbose_name=_t("MEMO"))
    is_stablecoin = models.BooleanField(default=False, verbose_name=_t("Стейблкоин"))

    # Иконки (либо файл, либо URL)
    icon_file = models.ImageField(upload_to="asset_icons/", blank=True, null=True, verbose_name=_t("Иконка (файл)"))
    icon_url = models.URLField(blank=True, default="", verbose_name=_t("Иконка (URL)"))

    # Как ПЛ называет эту запись (для отладки/маппинга)
    provider_symbol = models.CharField(max_length=128, blank=True, default="", verbose_name="Provider symbol")
    provider_chain = models.CharField(max_length=128, blank=True, default="", verbose_name="Provider chain")

    status_note = models.CharField(max_length=255, blank=True, default="", verbose_name=_t("Комментарий к статусу"))
    raw_metadata = models.JSONField(default=dict, blank=True, verbose_name=_t("Сырое описание от ПЛ"))

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_t("Создано"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_t("Обновлено"))

    class Meta:
        verbose_name = _t("Актив ПЛ")
        verbose_name_plural = _t("Активы ПЛ")
        ordering = ["exchange", "asset_code", "chain_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["exchange", "asset_code", "chain_code"],
                name="uniq_exchange_asset_chain",
            ),
        ]
        indexes = [
            models.Index(fields=["exchange", "asset_code"]),
            models.Index(fields=["exchange", "chain_code"]),
            models.Index(fields=["-updated_at"]),
        ]

    # ---- helpers ----

    def __str__(self) -> str:
        return f"{self.exchange.provider} · {self.asset_code}@{self.chain_code}"

    @property
    def deposit_open(self) -> bool:
        ex = self.exchange
        return bool(self.D and self.AD and getattr(ex, "is_available", True) and getattr(ex, "can_receive", True))

    @property
    def withdraw_open(self) -> bool:
        ex = self.exchange
        return bool(self.W and self.AW and getattr(ex, "is_available", True) and getattr(ex, "can_send", True))

    def clean(self):
        # Нормализация кодов
        if self.asset_code:
            self.asset_code = self.asset_code.strip().upper()
        if self.chain_code:
            self.chain_code = self.chain_code.strip().upper()

        # Кламп точностей
        max_dec = int(getattr(settings, "DECIMAL_AMOUNT_DEC_PLACES", 10))
        if self.amount_precision < 0:
            self.amount_precision = 0
        if self.amount_precision > max_dec:
            self.amount_precision = max_dec
        if self.amount_precision_display < 0:
            self.amount_precision_display = 0
        if self.amount_precision_display > max_dec:
            self.amount_precision_display = max_dec

        # Вывод не меньше ввода
        if self.confirmations_withdraw < self.confirmations_deposit:
            self.confirmations_withdraw = self.confirmations_deposit

        # Для крипты депозитное подтверждение минимум 1
        if self.asset_kind == AssetKind.CRYPTO and self.confirmations_deposit < 1:
            self.confirmations_deposit = 1
            if self.confirmations_withdraw < 1:
                self.confirmations_withdraw = 1

        # Лимиты: min <= max (0 — выключает ограничение)
        def _check_min_max(min_field: str, max_field: str, title: str):
            from decimal import Decimal as D
            min_v = getattr(self, min_field) or D("0")
            max_v = getattr(self, max_field) or D("0")
            if min_v > 0 and max_v > 0 and min_v > max_v:
                raise models.ValidationError({
                    min_field: _t("{title}: минимальное значение не может быть больше максимума.").format(title=title)
                })

        _check_min_max("deposit_min", "deposit_max", _t("Лимиты ввода"))
        _check_min_max("withdraw_min", "withdraw_max", _t("Лимиты вывода"))

        if self.nominal <= 0:
            raise models.ValidationError({"nominal": _t("Номинал должен быть больше нуля.")})
