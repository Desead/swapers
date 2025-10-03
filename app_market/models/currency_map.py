from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _t


class CurrencyMatchKind(models.TextChoices):
    EXACT = "EXACT", "Exact"
    REGEX = "REGEX", "Regex"
    SPLIT = "SPLIT", "Split"
    CUSTOM = "CUSTOM", "Custom"


class CurrencyMap(models.Model):
    """
    Нормализация сырых обозначений монет/сетей у конкретного ПЛ → к нашим asset_code/chain_code.
    Примеры raw: XBT, ERCUSDT, USDT-TRC20, ETH/USDT, RUB-SBER ...
    """

    exchange = models.ForeignKey(
        "app_market.Exchange",
        on_delete=models.CASCADE,
        related_name="currency_maps",
        db_index=True,
        verbose_name=_t("Поставщик"),
    )

    # Сырые обозначения от ПЛ
    raw_symbol = models.CharField(max_length=128, db_index=True, verbose_name="raw_symbol")
    raw_chain = models.CharField(max_length=128, blank=True, null=True, verbose_name="raw_chain")
    raw_pair = models.CharField(max_length=128, blank=True, null=True, verbose_name="raw_pair")  # на будущее (торговля)

    # Тип правила
    match_kind = models.CharField(
        max_length=10, choices=CurrencyMatchKind.choices, default=CurrencyMatchKind.EXACT, db_index=True
    )
    priority = models.IntegerField(default=0, db_index=True, verbose_name=_t("Приоритет"))

    # Параметры для REGEX/SPLIT/CUSTOM
    pattern = models.CharField(max_length=256, blank=True, default="", verbose_name="pattern/regex")
    asset_group_idx = models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="asset group index")
    chain_group_idx = models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="chain group index")
    split_delimiters = models.CharField(
        max_length=16, blank=True, default="", verbose_name="split delimiters (e.g. -/\\)"
    )
    left_is_asset = models.BooleanField(default=True, verbose_name=_t("Левая часть — это asset (для SPLIT)"))

    # Нормализованные коды (к нашим ExchangeAsset.asset_code / chain_code)
    norm_asset_code = models.CharField(max_length=32, verbose_name="asset_code (norm)")
    norm_chain_code = models.CharField(max_length=64, verbose_name="chain_code (norm)")

    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_t("Активно"))
    note = models.CharField(max_length=255, blank=True, default="", verbose_name=_t("Комментарий"))

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_t("Создано"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_t("Обновлено"))


    class Meta:
        verbose_name = _t("Маппинг обозначений валют")
        verbose_name_plural = _t("Маппинги обозначений валют")
        ordering = ["exchange", "-priority", "raw_symbol"]
        indexes = [
            models.Index(fields=["exchange", "raw_symbol"]),
            models.Index(fields=["exchange", "is_active", "-priority"]),
        ]

    def __str__(self) -> str:
        return f"{self.exchange.provider} · {self.raw_symbol}/{self.raw_chain or '-'} → {self.norm_asset_code}@{self.norm_chain_code}"
