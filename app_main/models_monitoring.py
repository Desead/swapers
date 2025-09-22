from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from django.db import models
from django.db.models import SET_NULL
from app_library.models import BannerAsset


class Monitoring(models.Model):
    class PartnerType(models.IntegerChoices):
        FROM_PROFIT = 1, _("От прибыли")
        FROM_GROSS = 2, _("От полной суммы")

    name = models.CharField(_("Название"), max_length=120, unique=True, default="Bestchange")
    link = models.URLField(_("Ссылка"), max_length=500, default="https://www.bestchange.ru/")

    number = models.PositiveIntegerField(_("Место на сайте"), default=100, )
    is_active = models.BooleanField(_("Включён"), default=True)

    banner_dark_asset = models.ForeignKey(
        BannerAsset,
        verbose_name=_("Баннер (тёмный) из библиотеки"),
        blank=True, null=True, on_delete=SET_NULL,
        related_name="monitorings_dark",
        limit_choices_to={"theme": "dark", },
    )
    banner_light_asset = models.ForeignKey(
        BannerAsset,
        verbose_name=_("Баннер (светлый) из библиотеки"),
        blank=True, null=True, on_delete=SET_NULL,
        related_name="monitorings_light",
        limit_choices_to={"theme": "light", },
    )

    percent = models.DecimalField(
        _("Партнёрский процент"),
        max_digits=20, decimal_places=8, default=Decimal("30"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )

    partner_type = models.IntegerField(
        _("Тип партнёрки"),
        choices=PartnerType.choices,
        default=PartnerType.FROM_PROFIT,
    )

    balance_usdt = models.DecimalField(
        _("Текущий Баланс (USDT)"),
        max_digits=20, decimal_places=8, editable=False,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text=_("Сумма к выплате с момента последнего вывода."),
    )

    total_profit_usdt = models.DecimalField(
        _("Общая прибыль (USDT)"),
        max_digits=20, decimal_places=8, editable=False,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text=_("Накопленная сумма за всё время."),
    )

    last_payout_at = models.DateTimeField(
        _("Дата последнего списания средств"),
        null=True, blank=True, editable=False,
    )
    last_payout_amount_usdt = models.DecimalField(
        _("Сумма последнего вывода (USDT)"),
        max_digits=20, decimal_places=8, editable=False,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )

    api_access = models.BooleanField(_("Доступ к API"), default=False)
    comment = models.TextField(_("Комментарий"), blank=True, default="")

    class Meta:
        verbose_name = _("Мониторинг")
        verbose_name_plural = _("Мониторинги")

    def __str__(self) -> str:
        return self.name

    @property
    def banner_dark_url(self):
        asset = getattr(self, "banner_dark_asset", None)
        try:
            return asset.file.url if asset and asset.file else None
        except Exception:
            return None

    @property
    def banner_light_url(self):
        asset = getattr(self, "banner_light_asset", None)
        try:
            return asset.file.url if asset and asset.file else None
        except Exception:
            return None

