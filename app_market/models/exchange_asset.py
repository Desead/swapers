from __future__ import annotations

from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _t


class AssetKind(models.TextChoices):
    CRYPTO = "CRYPTO", "Crypto"  # без i18n — это канонические ярлыки
    FIAT = "FIAT", "Fiat"
    PSP_MONEY = "PSP_MONEY", "PSP money"
    CASH = "CASH", "Cash"


class ExchangeAsset(models.Model):
    """
    Конкретная позиция у конкретного ПЛ: «монета + сеть/канал».
    Примеры: USDT@TRC20 (KuCoin), BTC@BTC (WhiteBIT), RUB@SBERBANK (Сбер), USD@PAYPAL.
    """

    # Привязка к поставщику ликвидности (ПЛ)
    exchange = models.ForeignKey(
        "app_market.Exchange",
        on_delete=models.CASCADE,
        related_name="assets",
        db_index=True,
        verbose_name=_t("Поставщик"),
    )

    # Идентификация (без i18n)
    asset_code = models.CharField(
        max_length=32,
        db_index=True,
        verbose_name="Asset code (e.g. BTC, USDT)",
    )
    asset_name = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name="Asset name (e.g. Bitcoin, Tether USD)",
    )
    chain_code = models.CharField(  # стандартное короткое имя сети/канала
        max_length=64,
        db_index=True,
        verbose_name="Chain/rail code (e.g. BTC, TRC20, ERC20, SEPA, SBERBANK)",
    )
    chain_display = models.CharField(  # как показывать сеть пользователю (опционально)
        max_length=128,
        blank=True,
        default="",
        verbose_name="Chain display (e.g. TRC-20, ERC-20, Сбербанк)",
    )

    # Название для внешнего API. Редактируемое. Если оставить пустым — сгенерируем.
    api_slug = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_t("API-метка (например USDT_TRC20)"),
        help_text=_t("Если оставить пустым — заполнится автоматически из ASSET_CHAIN."),
    )

    # Ручные флаги (включение/выключение руками оператора)
    D = models.BooleanField(default=True, verbose_name=_t("Ввод разрешён (ручной)"))
    W = models.BooleanField(default=True, verbose_name=_t("Вывод разрешён (ручной)"))

    # Автоматические флаги (обновляются адаптерами/проверками)
    AD = models.BooleanField(default=True, verbose_name=_t("Ввод доступен (авто)"))
    AW = models.BooleanField(default=True, verbose_name=_t("Вывод доступен (авто)"))

    # Подтверждения
    confirmations_deposit = models.PositiveIntegerField(
        default=0, verbose_name=_t("Подтверждений для ввода")
    )
    confirmations_withdraw = models.PositiveIntegerField(
        default=0, verbose_name=_t("Подтверждений для вывода")
    )

    # Комиссии/лимиты на ВВОД
    deposit_fee_percent = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Комиссия ввода, % (0=нет)"),
    )
    deposit_fee_fixed = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Комиссия ввода, фикс (0=нет)"),
    )
    deposit_min = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Мин. ввод (0=нет)"),
    )
    deposit_max = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Макс. ввод (0=нет)"),
    )
    # В USDT-эквиваленте (для массовых политик)
    deposit_min_usdt = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Мин. ввод (в USDT, 0=нет)"),
    )
    deposit_max_usdt = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Макс. ввод (в USDT, 0=нет)"),
    )

    # Комиссии/лимиты на ВЫВОД
    withdraw_fee_percent = models.DecimalField(
        max_digits=12, decimal_places=5, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Комиссия вывода, % (0=нет)"),
    )
    withdraw_fee_fixed = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Комиссия вывода, фикс (0=нет)"),
    )
    withdraw_min = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Мин. вывод (0=нет)"),
    )
    withdraw_max = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Макс. вывод (0=нет)"),
    )
    # В USDT-эквиваленте
    withdraw_min_usdt = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Мин. вывод (в USDT, 0=нет)"),
    )
    withdraw_max_usdt = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Макс. вывод (в USDT, 0=нет)"),
    )

    # Тип/точность/номинал
    asset_kind = models.CharField(
        max_length=16, choices=AssetKind.choices, default=AssetKind.CRYPTO, db_index=True,
        verbose_name=_t("Тип актива"),
    )
    amount_precision = models.PositiveSmallIntegerField(
        default=8, verbose_name=_t("Точность, знаков после запятой")
    )
    nominal = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.0000000001"))],
        verbose_name=_t("Номинал (по умолчанию 1)"),
    )

    # Резервы
    reserve_current = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Текущий резерв"),
    )
    reserve_min = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Мин. резерв (0=нет)"),
    )
    reserve_max = models.DecimalField(
        max_digits=28, decimal_places=10, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Макс. резерв (0=нет)"),
    )

    # Доп. атрибуты
    requires_memo = models.BooleanField(default=False, verbose_name=_t("Требуется MEMO/TAG"))
    memo_hint = models.CharField(max_length=128, blank=True, default="", verbose_name=_t("Подсказка по MEMO"))
    is_stablecoin = models.BooleanField(default=False, verbose_name=_t("Стейблкоин"))

    # Иконки (либо файл, либо URL)
    icon_file = models.ImageField(upload_to="asset_icons/", blank=True, null=True, verbose_name=_t("Иконка (файл)"))
    icon_url = models.URLField(blank=True, default="", verbose_name=_t("Иконка (URL)"))

    # Как ПЛ называет эту запись (для отладки/маппинга)
    provider_symbol = models.CharField(max_length=128, blank=True, default="", verbose_name="Provider symbol")
    provider_chain = models.CharField(max_length=128, blank=True, default="", verbose_name="Provider chain")

    status_note = models.CharField(max_length=255, blank=True, default="", verbose_name=_t("Комментарий к статусу"))
    raw_metadata = models.JSONField(default=dict, blank=True, verbose_name=_t("Сырое описание от ПЛ"))
    last_synced_at = models.DateTimeField(null=True, blank=True, verbose_name=_t("Последняя синхронизация"))

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_t("Создано"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_t("Обновлено"))

    class Meta:
        verbose_name = _t("Актив ПЛ (монета+сеть)")
        verbose_name_plural = _t("Активы ПЛ (монета+сеть)")
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
        # Эффективный доступ на ввод: ручной AND авто AND доступность ПЛ
        ex_avail = getattr(self.exchange, "is_available", True)
        return bool(self.D and self.AD and ex_avail)

    @property
    def withdraw_open(self) -> bool:
        ex_avail = getattr(self.exchange, "is_available", True)
        return bool(self.W and self.AW and ex_avail)

    def clean(self):
        # Нормализация кодов
        if self.asset_code:
            self.asset_code = self.asset_code.strip().upper()
        if self.chain_code:
            self.chain_code = self.chain_code.strip().upper()

        # Подтверждения: вывод не меньше ввода
        if self.confirmations_withdraw < self.confirmations_deposit:
            raise models.ValidationError({
                "confirmations_withdraw": _t("Подтверждений для вывода не может быть меньше, чем для ввода."),
            })

        # Лимиты: min <= max (0 — инвалидирует ограничение)
        def _check_min_max(min_field: str, max_field: str, title: str):
            min_v = getattr(self, min_field) or Decimal("0")
            max_v = getattr(self, max_field) or Decimal("0")
            if min_v > 0 and max_v > 0 and min_v > max_v:
                raise models.ValidationError({
                    min_field: _t("{title}: минимальное значение не может быть больше максимума.").format(title=title)
                })

        _check_min_max("deposit_min", "deposit_max", _t("Лимиты ввода"))
        _check_min_max("withdraw_min", "withdraw_max", _t("Лимиты вывода"))

        # nominal > 0
        if self.nominal <= 0:
            raise models.ValidationError({"nominal": _t("Номинал должен быть больше нуля.")})

    def save(self, *args, **kwargs):
        # Если api_slug не задан, генерируем ASSET_CHAIN
        if not self.api_slug:
            a = (self.asset_code or "").strip().upper()
            c = (self.chain_code or "").strip().upper()
            if a and c:
                self.api_slug = f"{a}_{c}"
        super().save(*args, **kwargs)

    # ВАЖНО: авто-политики (резервы/техработы) должны менять AD/AW,
    # а не D/W. Это реализуем во внешнем сервисе после операций,
    # чтобы иметь понятный аудит (не в save()).
