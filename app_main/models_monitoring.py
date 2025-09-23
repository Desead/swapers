from django.utils import timezone
from django.db.models import F
from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _t
from django.db import models
from django.db.models import SET_NULL
from app_library.models import BannerAsset


class Monitoring(models.Model):
    class PartnerType(models.IntegerChoices):
        FROM_PROFIT = 1, _t("От прибыли")
        FROM_GROSS = 2, _t("От полной суммы")

    name = models.CharField(_t("Название"), max_length=120, unique=True, default="Bestchange")
    link = models.URLField(_t("Ссылка"), max_length=500, default="https://www.bestchange.ru/")

    number = models.PositiveIntegerField(_t("Место на сайте"), default=100, )
    is_active = models.BooleanField(_t("Включён"), default=True)
    clicks_total = models.PositiveIntegerField(_t("Кликов всего"), default=0, editable=False)
    last_click_at = models.DateTimeField(_t("Последний клик"), blank=True, null=True, editable=False)

    banner_dark_asset = models.ForeignKey(
        BannerAsset,
        verbose_name=_t("Баннер (тёмный) из библиотеки"),
        blank=True, null=True, on_delete=SET_NULL,
        related_name="monitorings_dark",
        limit_choices_to={"theme": "dark", },
    )
    banner_light_asset = models.ForeignKey(
        BannerAsset,
        verbose_name=_t("Баннер (светлый) из библиотеки"),
        blank=True, null=True, on_delete=SET_NULL,
        related_name="monitorings_light",
        limit_choices_to={"theme": "light", },
    )

    percent = models.DecimalField(
        _t("Партнёрский процент"),
        max_digits=20, decimal_places=8, default=Decimal("30"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )

    partner_type = models.IntegerField(
        _t("Тип партнёрки"),
        choices=PartnerType.choices,
        default=PartnerType.FROM_PROFIT,
    )

    balance_usdt = models.DecimalField(
        _t("Текущий Баланс (USDT)"),
        max_digits=20, decimal_places=8, editable=False,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text=_t("Сумма к выплате с момента последнего вывода."),
    )

    total_profit_usdt = models.DecimalField(
        _t("Общая прибыль (USDT)"),
        max_digits=20, decimal_places=8, editable=False,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text=_t("Накопленная сумма за всё время."),
    )

    last_payout_at = models.DateTimeField(
        _t("Дата последнего списания средств"),
        null=True, blank=True, editable=False,
    )
    last_payout_amount_usdt = models.DecimalField(
        _t("Сумма последнего вывода (USDT)"),
        max_digits=20, decimal_places=8, editable=False,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )

    api_access = models.BooleanField(_t("Доступ к API"), default=False)
    title = models.CharField(verbose_name=_t("Оставить отзыв о нас"), max_length=120, null=True, blank=True, default=_t("Оставить отзыв о нас"))
    comment = models.TextField(_t("Комментарий"), blank=True, default="")

    class Meta:
        verbose_name = _t("Мониторинг")
        verbose_name_plural = _t("Мониторинги")

    def __str__(self) -> str:
        return self.name

    def register_click(self):
        """
        Безопасно инкрементим счётчик в БД (одной UPDATE),
        плюс фиксируем время клика.
        """
        Monitoring.objects.filter(pk=self.pk).update(
            clicks_total=F("clicks_total") + 1,
            last_click_at=timezone.now(),
        )

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
