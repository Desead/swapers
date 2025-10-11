from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _t

from django.conf import settings

AMOUNT_MAX_DIGITS = settings.DECIMAL_AMOUNT_INT_DIGITS + settings.DECIMAL_AMOUNT_DEC_PLACES
AMOUNT_DEC_PLACES = settings.DECIMAL_AMOUNT_DEC_PLACES

PERCENT_MAX_DIGITS = settings.DECIMAL_PERCENT_MAX_DIGITS
PERCENT_DEC_PLACES = settings.DECIMAL_PERCENT_PLACES_DB


class ExchangeKind(models.TextChoices):
    CEX = "CEX", _t("Классическая биржа (CEX)")
    DEX = "DEX", _t("Децентрализованная биржа (DEX)")
    PSP = "PSP", _t("Платёжная система (PSP)")
    WALLET = "WALLET", _t("Кошелёк")
    NODE = "NODE", _t("Нода")
    EXCHANGER = "EXCHANGER", _t("Обменники")
    BANK = "BANK", _t("Банк")
    MANUAL = "MANUAL", _t("Ручной обмен")
    OFFICE = "OFFICE", _t("Обмен в офисе")


class LiquidityProvider(models.TextChoices):
    # Биржи (CEX/DEX) — как были
    KUCOIN = "KUCOIN", "KuCoin"
    WHITEBIT = "WHITEBIT", "WhiteBIT"
    BYBIT = "BYBIT", "ByBit"
    HTX = "HTX", "HTX"
    MEXC = "MEXC", "MEXC"
    RAPIRA = "RAPIRA", "Rapira"
    BINANCE = "BINANCE", "Binance"
    COINBASE_EXCHANGE = "COINBASE_EXCHANGE", "Coinbase Exchange"
    UPBIT = "UPBIT", "Upbit"
    BITSTAMP = "BITSTAMP", "Bitstamp"
    BINGX = "BINGX", "BingX"
    BITFINEX = "BITFINEX", "Bitfinex"
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
    OFFICE = "OFFICE", "Office"


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

    # NODE
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

    LiquidityProvider.MANUAL: "",
    LiquidityProvider.OFFICE: "",
}


class Exchange(models.Model):
    provider = models.CharField(
        max_length=32,
        choices=LiquidityProvider.choices,
        default=LiquidityProvider.MANUAL,
        unique=True,
        db_index=True,
        verbose_name=_t("Название"),
    )

    exchange_kind = models.CharField(
        max_length=10,
        choices=ExchangeKind.choices,
        default=ExchangeKind.CEX,
        db_index=True,
        verbose_name=_t("Тип"),
        editable=False,
        help_text=_t("Устанавливается автоматически"),
    )

    is_available = models.BooleanField(
        default=True,
        editable=False,
        db_index=True,
        verbose_name=_t("Доступен"),
        help_text=_t("Изменяется автоматически (health-check, статусы API)."),
    )

    can_receive = models.BooleanField(default=True, verbose_name=_t("Приём средств"))
    can_send = models.BooleanField(default=True, verbose_name=_t("Вывод средств"))

    stablecoin = models.CharField(
        max_length=20,
        default="USDT",
        verbose_name=_t("Рабочий стейблкоин"),
        help_text=_t("Стейблкоин для расчётов, например: USDT."),
    )

    # --- Торговые комиссии (%, могут быть отрицательными) ---
    spot_taker_fee = models.DecimalField(
        max_digits=PERCENT_MAX_DIGITS, decimal_places=PERCENT_DEC_PLACES, default=Decimal("0.1"),
        verbose_name=_t("Спот: тейкер, %"),
        help_text=_t("Может быть отрицательной."),
        validators=[MaxValueValidator(Decimal("100"))],
    )
    spot_maker_fee = models.DecimalField(
        max_digits=PERCENT_MAX_DIGITS, decimal_places=PERCENT_DEC_PLACES, default=Decimal("0.1"),
        verbose_name=_t("Спот: мейкер, %"),
        help_text=_t("Может быть отрицательной."),
        validators=[MaxValueValidator(Decimal("100"))],
    )
    futures_taker_fee = models.DecimalField(
        max_digits=PERCENT_MAX_DIGITS, decimal_places=PERCENT_DEC_PLACES, default=Decimal("0.1"),
        verbose_name=_t("Фьючерсы: тейкер, %"),
        help_text=_t("Может быть отрицательной."),
        validators=[MaxValueValidator(Decimal("100"))],
    )
    futures_maker_fee = models.DecimalField(
        max_digits=PERCENT_MAX_DIGITS, decimal_places=PERCENT_DEC_PLACES, default=Decimal("0.1"),
        verbose_name=_t("Фьючерсы: мейкер, %"),
        help_text=_t("Может быть отрицательной."),
        validators=[MaxValueValidator(Decimal("100"))],
    )

    # --- Комиссии на ввод/вывод ---
    fee_deposit_percent = models.DecimalField(
        max_digits=PERCENT_MAX_DIGITS, decimal_places=PERCENT_DEC_PLACES, default=Decimal("0"),
        verbose_name=_t("Ввод: %"),
        validators=[MaxValueValidator(Decimal("100"))],
    )
    fee_deposit_fixed = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        verbose_name=_t("Ввод: фикс"),
    )
    # FIX: decimal_places для min-комиссии должен быть как у сумм (AMOUNT_DEC_PLACES)
    fee_deposit_min = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Ввод: мин. комиссия"),
    )
    fee_deposit_max = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Ввод: макс. комиссия"),
    )

    fee_withdraw_percent = models.DecimalField(
        max_digits=PERCENT_MAX_DIGITS, decimal_places=PERCENT_DEC_PLACES, default=Decimal("0"),
        verbose_name=_t("Вывод: %"),
        validators=[MaxValueValidator(Decimal("100"))],
    )
    fee_withdraw_fixed = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        verbose_name=_t("Вывод: фикс"),
    )
    fee_withdraw_min = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Вывод: мин. комиссия"),
    )
    fee_withdraw_max = models.DecimalField(
        max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_DEC_PLACES, default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name=_t("Вывод: макс. комиссия"),
    )

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
        return PROVIDER_PARTNER_LINKS.get(self.provider, "")

    def _auto_kind_from_provider(self) -> str:
        # PSP
        if self.provider in {
            LiquidityProvider.PAYPAL, LiquidityProvider.ADVCASH,
            LiquidityProvider.FIREKASSA, LiquidityProvider.APIRONE
        }:
            return ExchangeKind.PSP

        # DEX
        if self.provider in {LiquidityProvider.UNISWAP, LiquidityProvider.PANCAKESWAP}:
            return ExchangeKind.DEX

        # EXCHANGER
        if self.provider in {
            LiquidityProvider.CHANGENOW, LiquidityProvider.CHANGELLY,
            LiquidityProvider.FIXEDFLOAT, LiquidityProvider.QUICKEX,
            LiquidityProvider.ALFABIT
        }:
            return ExchangeKind.EXCHANGER

        # WALLET
        if self.provider in {
            LiquidityProvider.WESTWALLET, LiquidityProvider.TRUSTWALLET,
            LiquidityProvider.TRONWALLET, LiquidityProvider.ANTARCTICWALLET,
            LiquidityProvider.TELEGRAM_WALLET
        }:
            return ExchangeKind.WALLET

        # NODE
        if self.provider in {
            LiquidityProvider.BTC_NODE, LiquidityProvider.XMR_NODE,
            LiquidityProvider.USDT_NODE, LiquidityProvider.USDC_NODE,
            LiquidityProvider.DASH_NODE
        }:
            return ExchangeKind.NODE

        # BANK
        if self.provider in {
            LiquidityProvider.SBERBANK, LiquidityProvider.TBANK,
            LiquidityProvider.ALFABANK, LiquidityProvider.VTB
        }:
            return ExchangeKind.BANK

        if self.provider == LiquidityProvider.MANUAL:
            return ExchangeKind.MANUAL
        if self.provider == LiquidityProvider.OFFICE:
            return ExchangeKind.OFFICE

        return self.exchange_kind

    def clean(self):
        if self.fee_deposit_min and self.fee_deposit_max:
            if self.fee_deposit_max < self.fee_deposit_min:
                raise ValidationError({"fee_deposit_max": _t("Максимум не может быть меньше минимума.")})
        if self.fee_withdraw_min and self.fee_withdraw_max:
            if self.fee_withdraw_max < self.fee_withdraw_min:
                raise ValidationError({"fee_withdraw_max": _t("Максимум не может быть меньше минимума.")})

    def save(self, *args, **kwargs):
        mapped_kind = self._auto_kind_from_provider()
        if mapped_kind != self.exchange_kind:
            self.exchange_kind = mapped_kind

        if self.stablecoin:
            self.stablecoin = self.stablecoin.strip().upper()

        self.full_clean()
        super().save(*args, **kwargs)
