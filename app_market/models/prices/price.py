from django.db import models
from django.utils import timezone
from django.db.models import Q, CheckConstraint, Index
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _t


# NB: мы не считаем здесь "лучшее среди ПЛ" — только сырые L1 от каждого провайдера.
# Историю держим в БД (каждый апдейт = новая строка), "живое" — в Redis.

class VenueType(models.TextChoices):
    CEX = "CEX", _t("Криптобиржа (CEX)")
    DEX = "DEX", _t("Децентрализованная биржа (DEX)")
    PSP = "PSP", _t("Платёжный провайдер / фиат")
    OTC = "OTC", _t("OTC / ручная котировка")
    MANUAL = "MANUAL", _t("Ручной источник")


class PriceStatus(models.TextChoices):
    OK = "OK", _t("ОК")
    STALE = "STALE", _t("Устарела")
    DEGRADED = "DEGRADED", _t("Деградация качества")


class PriceL1(models.Model):
    """
    Нормализованная L1-котировка: лучшая цена покупки/продажи по провайдеру и паре.
    Используется как «контракт» данных: все источники приводим к этому формату.
    Частые обновления живут в Redis; в БД храним сэмплы/лог, статистику и видимость в админке.
    """

    # Кто дал котировку
    provider = models.ForeignKey(
        "app_market.Exchange",
        on_delete=models.PROTECT,
        related_name="prices_l1",
        verbose_name=_t("Поставщик ликвидности"),
        help_text=_t("Связь на Exchange (ПЛ)."),
    )
    venue_type = models.CharField(
        max_length=10,
        choices=VenueType.choices,
        verbose_name=_t("Тип площадки"),
        help_text=_t("CEX/DEX/PSP/OTC/MANUAL — для аналитики и SLA по свежести."),
    )

    # Какая пара (внутренние единые идентификаторы активов)
    base_asset = models.ForeignKey(
        "app_market.ExchangeAsset",  # если у тебя иное имя модели (Coin/Currency) — поменяй строковый путь
        on_delete=models.PROTECT,
        related_name="prices_l1_base",
        verbose_name=_t("Базовый актив"),
    )
    quote_asset = models.ForeignKey(
        "app_market.ExchangeAsset",
        on_delete=models.PROTECT,
        related_name="prices_l1_quote",
        verbose_name=_t("Котируемый актив"),
    )

    # Оригинальные обозначения у провайдера (для трассировки)
    src_symbol = models.CharField(
        max_length=64,
        verbose_name=_t("Исходный символ у ПЛ"),
        help_text=_t("Напр. BTCUSDT, BTC-USD, pool_id для DEX."),
    )
    src_base_code = models.CharField(
        max_length=32,
        verbose_name=_t("Исходный код базового"),
        help_text=_t("Ticker/contract у провайдера. Для DEX — адрес токена."),
    )
    src_quote_code = models.CharField(
        max_length=32,
        verbose_name=_t("Исходный код котируемого"),
        help_text=_t("Ticker/contract у провайдера. Для DEX — адрес токена."),
    )

    # Цены L1
    bid = models.DecimalField(
        max_digits=38, decimal_places=18,
        validators=[MinValueValidator(0)],
        verbose_name=_t("Bid"),
        help_text=_t("Лучшая цена, по которой мы МОЖЕМ продать базовый актив (клиент покупает)."),
    )
    ask = models.DecimalField(
        max_digits=38, decimal_places=18,
        validators=[MinValueValidator(0)],
        verbose_name=_t("Ask"),
        help_text=_t("Лучшая цена, по которой мы МОЖЕМ купить базовый актив (клиент продаёт)."),
    )
    last = models.DecimalField(
        max_digits=38, decimal_places=18,
        null=True, blank=True,
        verbose_name=_t("Last"),
        help_text=_t("Последняя сделка у источника, если доступно."),
    )

    # Комиссии провайдера (для расчёта эффективной цены на шаге 2; bps = 1/10000)
    fee_taker_bps = models.PositiveIntegerField(
        default=0,
        verbose_name=_t("Taker комиссия, bps"),
        help_text=_t("Торговая комиссия taker в базисных пунктах; может уточняться при расчёте."),
    )
    fee_maker_bps = models.PositiveIntegerField(
        default=0,
        verbose_name=_t("Maker комиссия, bps"),
        help_text=_t("Необязательная, если используем лимитные стратегии."),
    )

    # Метки времени и последовательность
    ts_src = models.DateTimeField(
        verbose_name=_t("Время у источника"),
        help_text=_t("Timestamp, который пришёл от ПЛ (сервер источника)."),
    )
    ts_ingest = models.DateTimeField(
        default=timezone.now,
        verbose_name=_t("Время приёма"),
        help_text=_t("Когда наша система приняла и нормализовала котировку."),
    )
    seq = models.BigIntegerField(
        null=True, blank=True,
        verbose_name=_t("Последовательность/offset"),
        help_text=_t("Для WS/стримов (last_update_id, trade_id и т.п.), если доступно."),
    )
    latency_ms = models.PositiveIntegerField(
        default=0,
        verbose_name=_t("Задержка, мс"),
        help_text=_t("Оценка (ingest - ts_src) в миллисекундах."),
    )

    # Качество данных
    status = models.CharField(
        max_length=12,
        choices=PriceStatus.choices,
        default=PriceStatus.OK,
        verbose_name=_t("Статус"),
        help_text=_t("OK/STALE/DEGRADED по SLA свежести и валидациям."),
    )
    quality_note = models.CharField(
        max_length=255, null=True, blank=True,
        verbose_name=_t("Комментарий к качеству"),
        help_text=_t("Почему деградация/устаревание, если есть."),
    )

    # Сырые детали (на будущее: размер лота, best sizes, raw payload и т.п.)
    extras = models.JSONField(
        default=dict, blank=True,
        verbose_name=_t("Доп. данные"),
        help_text=_t("Сырые поля источника: best sizes, quoteId, pool reserves и т.п."),
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_t("Создано"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_t("Обновлено"))

    class Meta:
        db_table = "market_price_l1"
        verbose_name = _t("L1-котировка (bid/ask)")
        verbose_name_plural = _t("L1-котировки (bid/ask)")
        # Часто фильтруем по провайдеру, паре, времени источника
        indexes = [
            Index(fields=["provider", "base_asset", "quote_asset", "-ts_src"], name="idx_price_l1_src"),
            Index(fields=["venue_type", "base_asset", "quote_asset", "-ts_src"], name="idx_price_l1_venue"),
            Index(fields=["status", "-ts_ingest"], name="idx_price_l1_status"),
        ]
        constraints = [
            # ask >= bid и цены неотрицательны
            CheckConstraint(check=Q(ask__gte=models.F("bid")), name="price_l1_ask_ge_bid"),
            CheckConstraint(check=Q(bid__gte=0) & Q(ask__gte=0), name="price_l1_non_negative"),
        ]
        # На масштабе: переводим таблицу в Timescale/partition по ts_src (вне Django)

    def __str__(self) -> str:
        return f"[{self.provider_id}/{self.venue_type}] {self.base_asset_id}/{self.quote_asset_id} bid={self.bid} ask={self.ask} @ {self.ts_src}"

    @property
    def mid(self):
        # Удобный доступ к mid, если нужен в админке/отчётах
        return (self.bid + self.ask) / 2 if self.bid is not None and self.ask is not None else None

    def is_stale(self, now=None, ttl_seconds: int = 10) -> bool:
        now = now or timezone.now()
        return (now - self.ts_src).total_seconds() > ttl_seconds
