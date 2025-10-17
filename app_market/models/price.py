from __future__ import annotations

from django.db import models
from django.db.models import Q, F, CheckConstraint, Index
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _t


class PriceL1(models.Model):
    """
    Сырые L1-котировки (best bid/ask/last) по каждой ПЛ и торговой паре у ЭТОГО провайдера.
    ВАЖНО: здесь нет маппинга на наши внутренние активы — только то, как пара называется у ПЛ.
    История хранится как «журнал» (каждая значимая точка — новая строка); «горячее» держим в Redis.
    """

    # -- КТО дал котировку (ПЛ) --
    provider = models.ForeignKey(
        "app_market.Exchange",
        on_delete=models.PROTECT,
        related_name="prices_l1",
        db_index=True,
        verbose_name=_t("Поставщик ликвидности"),
        help_text=_t("Связь на Exchange (ПЛ). Вид площадки см. provider.exchange_kind."),
    )

    # -- КАК называется пара у провайдера (без маппинга) --
    src_symbol = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name=_t("Исходный символ у ПЛ"),
        help_text=_t("Напр. BTCUSDT, BTC_USDT, ETH-BTC и т.п."),
    )
    src_base_code = models.CharField(
        max_length=32,
        db_index=True,
        verbose_name=_t("Код базового у ПЛ"),
        help_text=_t("Ticker/contract базового актива у провайдера."),
    )
    src_quote_code = models.CharField(
        max_length=32,
        db_index=True,
        verbose_name=_t("Код котируемого у ПЛ"),
        help_text=_t("Ticker/contract котируемого актива у провайдера."),
    )

    # -- Цены L1 --
    bid = models.DecimalField(
        max_digits=38,
        decimal_places=18,
        validators=[MinValueValidator(0)],
        verbose_name=_t("Bid"),
        help_text=_t("Лучшая цена, по которой мы МОЖЕМ продать базовый актив (клиент покупает)."),
    )
    ask = models.DecimalField(
        max_digits=38,
        decimal_places=18,
        validators=[MinValueValidator(0)],
        verbose_name=_t("Ask"),
        help_text=_t("Лучшая цена, по которой мы МОЖЕМ купить базовый актив (клиент продаёт)."),
    )
    last = models.DecimalField(
        max_digits=38,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name=_t("Last"),
        help_text=_t("Последняя сделка у источника, если доступно."),
    )

    # -- Комиссии (снимок на момент котировки, в базисных пунктах = 1/10000) --
    class FeeSource(models.TextChoices):
        PUBLIC = "PUBLIC", _t("Публичный API")
        PRIVATE = "PRIVATE", _t("Приватный API")
        PAIR = "PAIR", _t("Переписано из пары/инструмента")
        UNKNOWN = "UNKNOWN", _t("Неизвестно")

    fee_taker_bps = models.PositiveIntegerField(
        default=0,
        verbose_name=_t("Taker комиссия, bps"),
        help_text=_t("Если приватные комиссии доступны — сохраняем их, они важнее публичных."),
    )
    fee_maker_bps = models.PositiveIntegerField(
        default=0,
        verbose_name=_t("Maker комиссия, bps"),
        help_text=_t("Для лимитных стратегий; может быть ноль, если не используем."),
    )
    fee_source = models.CharField(
        max_length=16,
        choices=FeeSource.choices,
        default=FeeSource.UNKNOWN,
        verbose_name=_t("Источник комиссий"),
    )

    # -- Тайминги/последовательность --
    ts_src = models.DateTimeField(
        db_index=True,
        verbose_name=_t("Время у источника"),
        help_text=_t("Timestamp от ПЛ (сервер источника); если не приходит — подставляем ingest."),
    )
    ts_ingest = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name=_t("Время приёма"),
        help_text=_t("Когда наша система приняла/нормализовала котировку."),
    )
    seq = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_t("Последовательность/offset"),
        help_text=_t("Для WS/стримов (last_update_id, trade_id и т.п.), если есть."),
    )
    latency_ms = models.PositiveIntegerField(
        default=0,
        verbose_name=_t("Задержка, мс"),
        help_text=_t("Оценка (ingest - ts_src) в миллисекундах."),
    )

    # -- Сырые детали (best sizes, quoteId, payload и пр.) --
    extras = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_t("Доп. данные"),
        help_text=_t("Сырые поля источника: best sizes, quoteId, pool reserves и пр."),
    )

    # -- Служебные поля --
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_t("Создано"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_t("Обновлено"))

    class Meta:
        db_table = "market_price_l1"
        verbose_name = _t("L1-котировка (bid/ask)")
        verbose_name_plural = _t("L1-котировки (bid/ask)")
        indexes = [
            # частые выборки: по провайдеру + паре + последним котировкам
            Index(fields=["provider", "src_base_code", "src_quote_code", "-ts_src"], name="idx_l1_prov_pair_src"),
            Index(fields=["src_symbol", "-ts_src"], name="idx_l1_symbol_src"),
            Index(fields=["-ts_ingest"], name="idx_l1_ingest_desc"),
        ]
        constraints = [
            CheckConstraint(
                condition=Q(ask__gte=F("bid")),
                name="price_l1_ask_ge_bid",
            ),
            CheckConstraint(
                condition=Q(bid__gte=0) & Q(ask__gte=0),
                name="price_l1_non_negative",
            ),
        ]
        ordering = ["-ts_src", "-id"]

    # --------- Удобства ---------

    def __str__(self) -> str:
        return f"[{self.provider_id}] {self.src_base_code}/{self.src_quote_code} bid={self.bid} ask={self.ask} @ {self.ts_src}"

    @property
    def pair(self) -> str:
        return f"{self.src_base_code}/{self.src_quote_code}"

    @property
    def mid(self):
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2

    @property
    def exchange_kind(self) -> str:
        """
        Вид площадки берём из связанного Exchange (CEX/DEX/PSP/...).
        Поле в модели не дублируем.
        """
        return getattr(self.provider, "exchange_kind", "")
