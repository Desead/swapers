from decimal import Decimal
from django.db import models
from django.utils.translation import gettext_lazy as _t


class Exchange(models.Model):
    name = models.CharField(
        max_length=120,
        unique=True,
        verbose_name=_t("Название биржи"),
    )

    # 3) Автоматический флаг доступности (редактировать нельзя в форме)
    is_available = models.BooleanField(
        default=True,
        editable=False,
        db_index=True,
        verbose_name=_t("Биржа доступна"),
        help_text=_t("Заполняется и изменяется автоматически (health-check, статусы API)."),
    )

    # 5) Режимы работы: по умолчанию оба включены
    can_receive = models.BooleanField(
        default=True,
        verbose_name=_t("Приём средств"),
    )
    can_send = models.BooleanField(
        default=True,
        verbose_name=_t("Отдача средств"),
    )

    # 6) Рабочий стейблкоин (не пустой, по умолчанию USDT)
    stablecoin = models.CharField(
        max_length=20,
        default="USDT",
        verbose_name=_t("Рабочий стейблкоин"),
        help_text=_t("Стейблкоин для расчётов, например: USDT."),
    )

    # 7) Комиссии (могут быть отрицательными), по умолчанию 0.1
    spot_taker_fee = models.DecimalField(
        max_digits=7, decimal_places=4, default=Decimal("0.1"),
        verbose_name=_t("Спот: тейкер, %"),
        help_text=_t("Комиссия тейкера на споте"),
    )
    spot_maker_fee = models.DecimalField(
        max_digits=7, decimal_places=4, default=Decimal("0.1"),
        verbose_name=_t("Спот: мейкер, %"),
        help_text=_t("комиссия мейкера на споте"),
    )
    futures_taker_fee = models.DecimalField(
        max_digits=7, decimal_places=4, default=Decimal("0.1"),
        verbose_name=_t("Фьючерсы: тейкер, %"),
        help_text=_t("Комиссия тейкера на фьючерсах"),
    )
    futures_maker_fee = models.DecimalField(
        max_digits=7, decimal_places=4, default=Decimal("0.1"),
        verbose_name=_t("Фьючерсы: мейкер, %"),
        help_text=_t("Комиссия мейкера на фьючерсах."),
    )

    # 8) Флаг "цены на главную"
    show_prices_on_home = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_t("Показывать цены на главной"),
    )

    class Meta:
        verbose_name = _t("Биржа")
        verbose_name_plural = _t("Биржи")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        # Нормализуем stablecoin (в верхний регистр, без пробелов)
        if self.stablecoin:
            self.stablecoin = self.stablecoin.strip().upper()
        super().save(*args, **kwargs)
