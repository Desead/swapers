from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _t


class ExchangeKind(models.TextChoices):
    CEX = "CEX", _t("Классическая биржа (CEX)")
    DEX = "DEX", _t("Децентрализованная биржа (DEX)")
    PSP = "PSP", _t("Платёжная система (PSP)")
    WALLET = "WALLET", _t("Кошелёк")
    NODE = "NODE", _t("Нода")
    EXCHANGER = "EXCHANGER", _t("Обменники")
    BANK = "BANK", _t("Банк")
    MANUAL = "MANUAL", _t("Ручной обмен (возможно в офисе)")


class LiquidityProvider(models.TextChoices):
    # Биржи (CEX/DEX) — как были
    KUCOIN = "KUCOIN", "KuCoin"
    WHITEBIT = "WHITEBIT", "WhiteBIT"
    BYBIT = "BYBIT", "ByBit"
    RAPIRA = "RAPIRA", "Rapira"
    MEXC = "MEXC", "MEXC"
    BINANCE = "BINANCE", "Binance"
    COINBASE_EXCHANGE = "COINBASE_EXCHANGE", "Coinbase Exchange"
    UPBIT = "UPBIT", "Upbit"
    BITSTAMP = "BITSTAMP", "Bitstamp"
    BINGX = "BINGX", "BingX"
    BITFINEX = "BITFINEX", "Bitfinex"
    HTX = "HTX", "HTX"
    GATEIO = "GATEIO", "Gate.io"
    BITGET = "BITGET", "Bitget"
    OKX = "OKX", "OKX"
    GEMINI = "GEMINI", "Gemini"
    LBANK = "LBANK", "LBank"
    UNISWAP = "UNISWAP", "Uniswap"
    PANCAKESWAP = "PANCAKESWAP", "PancakeSwap"

    # Платёжные системы (PSP)
    PAYPAL = "PAYPAL", "PayPal"
    ADVCASH = "ADVCASH", "Advanced Cash"
    FIREKASSA = "FIREKASSA", "FireKassa"
    APIRONE = "APIRONE", "Apirone"

    # Обменники (EXCHANGER)
    CHANGENOW = "CHANGENOW", "ChangeNOW"
    CHANGELLY = "CHANGELLY", "Changelly"
    FIXEDFLOAT = "FIXEDFLOAT", "ff.io"
    QUICKEX = "QUICKEX", "Quickex"
    ALFABIT = "ALFABIT", "Alfabit"

    # Кошельки (WALLET)
    WESTWALLET = "WESTWALLET", "WestWallet"
    TRUSTWALLET = "TRUSTWALLET", "Trust Wallet"
    TRONWALLET = "TRONWALLET", "Tron Wallet"
    ANTARCTICWALLET = "ANTARCTICWALLET", "Antarctic Wallet"
    TELEGRAM_WALLET = "TELEGRAM_WALLET", "Telegram Wallet"

    # Ноды (NODE)
    BTC_NODE = "BTC_NODE", "BTC Node"
    XMR_NODE = "XMR_NODE", "XMR Node"
    USDT_NODE = "USDT_NODE", "USDT Node"
    USDC_NODE = "USDC_NODE", "USDC Node"
    DASH_NODE = "DASH_NODE", "DASH Node"

    # Банки (BANK)
    SBERBANK = "SBERBANK", "Сбербанк"
    TBANK = "TBANK", "ТБанк"
    ALFABANK = "ALFABANK", "Альфабанк"
    VTB = "VTB", "ВТБ банк"

    # Ручной режим
    MANUAL = "MANUAL", "Manual"


PROVIDER_PARTNER_LINKS: dict[str, str] = {
    # CEX
    LiquidityProvider.KUCOIN: "https://www.kucoin.com/",
    LiquidityProvider.WHITEBIT: "https://whitebit.com/",
    LiquidityProvider.BYBIT: "https://www.bybit.com/",
    LiquidityProvider.RAPIRA: "https://rapira.net/?ref=53BE",
    LiquidityProvider.MEXC: "https://www.mexc.com/",
    LiquidityProvider.BINANCE: "https://www.binance.com/",
    LiquidityProvider.COINBASE_EXCHANGE: "https://exchange.coinbase.com/",
    LiquidityProvider.UPBIT: "https://upbit.com/",
    LiquidityProvider.BITSTAMP: "https://www.bitstamp.net/",
    LiquidityProvider.BINGX: "https://bingx.com/",
    LiquidityProvider.BITFINEX: "https://www.bitfinex.com/",
    LiquidityProvider.HTX: "https://www.htx.com/",
    LiquidityProvider.GATEIO: "https://www.gate.io/",
    LiquidityProvider.BITGET: "https://www.bitget.com/",
    LiquidityProvider.OKX: "https://www.okx.com/",
    LiquidityProvider.GEMINI: "https://www.gemini.com/",
    LiquidityProvider.LBANK: "https://www.lbank.com/",
    # DEX
    LiquidityProvider.UNISWAP: "https://app.uniswap.org/",
    LiquidityProvider.PANCAKESWAP: "https://pancakeswap.finance/",
    # PSP
    LiquidityProvider.PAYPAL: "https://www.paypal.com/",
    LiquidityProvider.ADVCASH: "https://advcash.com/",
    LiquidityProvider.FIREKASSA: "https://firekassa.com/",
    LiquidityProvider.APIRONE: "https://apirone.com/",
    # EXCHANGER
    LiquidityProvider.CHANGENOW: "https://changenow.io/",
    LiquidityProvider.CHANGELLY: "https://changelly.com/",
    LiquidityProvider.FIXEDFLOAT: "https://ff.io/?ref=62h6ezbd",
    LiquidityProvider.QUICKEX: "https://quickex.io/",
    LiquidityProvider.ALFABIT: "https://alfabit.org/",

    # WALLET
    LiquidityProvider.WESTWALLET: "https://westwallet.io/",
    LiquidityProvider.TRUSTWALLET: "https://trustwallet.com/",
    LiquidityProvider.TRONWALLET: "https://www.tronlink.org/",
    LiquidityProvider.ANTARCTICWALLET: "https://antarcticwallet.com/",
    LiquidityProvider.TELEGRAM_WALLET: "https://t.me/wallet",
    # NODE (даём официальные сайты проектов)
    LiquidityProvider.BTC_NODE: "https://bitcoin.org/",
    LiquidityProvider.XMR_NODE: "https://www.getmonero.org/",
    LiquidityProvider.USDT_NODE: "https://tether.to/",
    LiquidityProvider.USDC_NODE: "https://www.circle.com/usdc",
    LiquidityProvider.DASH_NODE: "https://www.dash.org/",
    # BANK
    LiquidityProvider.SBERBANK: "https://www.sberbank.ru/",
    LiquidityProvider.TBANK: "https://www.tbank.ru/",
    LiquidityProvider.ALFABANK: "https://alfabank.ru/",
    LiquidityProvider.VTB: "https://www.vtb.ru/",
    # MANUAL — пусто (нет внешнего сайта)
    LiquidityProvider.MANUAL: "",
}


class Exchange(models.Model):
    # Фиксированный список провайдеров (одна запись на провайдера)
    provider = models.CharField(
        max_length=20,
        choices=LiquidityProvider.choices,
        default=LiquidityProvider.MANUAL,
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
        help_text=_t("Устанавливается автоматически"),
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
        default=False, db_index=True, verbose_name=_t("Цены")
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

    @property
    def partner_url(self) -> str:
        """Партнёрская (или просто официальная) ссылка для провайдера — из кода, только для чтения."""
        return PROVIDER_PARTNER_LINKS.get(self.provider, "")

    # Валидации/нормализации
    def _auto_kind_from_provider(self) -> str:
        if self.provider in {LiquidityProvider.PAYPAL, LiquidityProvider.ADVCASH}:
            return ExchangeKind.PSP
        if self.provider in {LiquidityProvider.UNISWAP, LiquidityProvider.PANCAKESWAP}:
            return ExchangeKind.DEX
        if self.provider == LiquidityProvider.MANUAL:
            return ExchangeKind.MANUAL
        return self.exchange_kind

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
