from django.contrib import admin
from django import forms
from django.utils.translation import gettext_lazy as _t
from app_market.models import Exchange, ExchangeApiKey
from django.utils.html import format_html


@admin.register(Exchange)
class ExchangeAdmin(admin.ModelAdmin):
    save_on_top = True

    list_display = (
        "provider", "is_available",
        "can_receive", "can_send", "stablecoin",
        "spot_taker_fee", "spot_maker_fee",
        "futures_taker_fee", "futures_maker_fee",
        "show_prices_on_home",
    )
    list_filter = (
        "provider", "is_available", "exchange_kind",
        "can_receive", "can_send", "show_prices_on_home",
    )
    search_fields = ("provider",)
    readonly_fields = ("is_available", "exchange_kind", "partner_link",)

    fieldsets = (
        (_t("Общее"), {
            "fields": (("provider", "is_available",), "exchange_kind", "webhook_endpoint", "partner_link",)
        }),
        (_t("Режимы работы"), {"fields": (("can_receive", "can_send"),)}),
        (_t("Стейблкоин расчётов"), {"fields": ("stablecoin",)}),

        (_t("Торговые комиссии"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("spot_taker_fee", "spot_maker_fee"),
                ("futures_taker_fee", "futures_maker_fee"),
            ),
            "description": _t("Значения в процентах, могут быть отрицательными."),
        }),

        (_t("Комиссии на ввод и вывод"), {
            "description": _t("Если в поле комиссии стоит значение = 0, значит данная комиссия не используется"),
            "classes": ("wide", "collapse"),
            "fields": (
                ("fee_deposit_percent", "fee_withdraw_percent"),
                ("fee_deposit_fixed", "fee_withdraw_fixed"),
                ("fee_deposit_min", "fee_withdraw_min"),
                ("fee_deposit_max", "fee_withdraw_max"),
            )
        }),

        (_t("Отображение"), {
            "description": _t(
                "Цены с этого поставщика ликвидности будут отображаться на главной странице. "
                "Можно одновременно выбирать несколько разных поставщиков, например биржу+банк и т.д."
            ),
            "fields": ("show_prices_on_home",)
        }),
    )

    def partner_link(self, obj):
        url = getattr(obj, "partner_url", "") or ""
        if not url:
            return "—"
        label = _t("Перейти на сайт {name}").format(name=obj.get_provider_display())
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', url, label)

    partner_link.short_description = _t("URL")

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        """
        Группируем выпадающий список provider в админке.
        """
        if db_field.name != "provider":
            return super().formfield_for_choice_field(db_field, request, **kwargs)

        field = super().formfield_for_choice_field(db_field, request, **kwargs)
        from app_market.models.exchange import LiquidityProvider
        labels = dict(LiquidityProvider.choices)

        def pick(values):
            return [(v, labels[v]) for v in values if v in labels]

        groups = [
            (_t("Ручной режим"), pick([
                LiquidityProvider.MANUAL,
            ])),
            (_t("Централизованные биржи (CEX)"), pick([
                LiquidityProvider.KUCOIN,
                LiquidityProvider.WHITEBIT,
                LiquidityProvider.BYBIT,
                LiquidityProvider.RAPIRA,
                LiquidityProvider.MEXC,
                LiquidityProvider.BINANCE,
                LiquidityProvider.COINBASE_EXCHANGE,
                LiquidityProvider.UPBIT,
                LiquidityProvider.BITSTAMP,
                LiquidityProvider.BINGX,
                LiquidityProvider.BITFINEX,
                LiquidityProvider.HTX,
                LiquidityProvider.GATEIO,
                LiquidityProvider.BITGET,
                LiquidityProvider.OKX,
                LiquidityProvider.GEMINI,
                LiquidityProvider.LBANK,
            ])),
            (_t("Децентрализованные (DEX)"), pick([
                LiquidityProvider.UNISWAP,
                LiquidityProvider.PANCAKESWAP,
            ])),
            (_t("Обменники (EXCHANGER)"), pick([
                LiquidityProvider.CHANGENOW,
                LiquidityProvider.CHANGELLY,
                LiquidityProvider.FIXEDFLOAT,
                LiquidityProvider.QUICKEX,
            ])),
            (_t("Кошельки (WALLET)"), pick([
                LiquidityProvider.WESTWALLET,
                LiquidityProvider.TRUSTWALLET,
                LiquidityProvider.TRONWALLET,
                LiquidityProvider.ANTARCTICWALLET,
                LiquidityProvider.TELEGRAM_WALLET,
            ])),
            (_t("Банки (BANK)"), pick([
                LiquidityProvider.SBERBANK,
                LiquidityProvider.ALFABANK,
                LiquidityProvider.VTB,
                LiquidityProvider.TBANK,
            ])),
            (_t("Ноды (NODE)"), pick([
                LiquidityProvider.BTC_NODE,
                LiquidityProvider.XMR_NODE,
                LiquidityProvider.USDT_NODE,
                LiquidityProvider.USDC_NODE,
                LiquidityProvider.DASH_NODE,
            ])),
            (_t("Платёжные системы (PSP)"), pick([
                LiquidityProvider.PAYPAL,
                LiquidityProvider.ADVCASH,
                LiquidityProvider.FIREKASSA,
                LiquidityProvider.APIRONE,
            ])),
        ]

        field.choices = [g for g in groups if g[1]]
        return field


class ExchangeApiKeyAdminForm(forms.ModelForm):
    class Meta:
        model = ExchangeApiKey
        fields = (
            "exchange", "label",
            "api_key", "api_secret", "api_passphrase",
            "is_enabled",
        )
        widgets = {
            "api_key": forms.PasswordInput(render_value=False),
            "api_secret": forms.PasswordInput(render_value=False),
            "api_passphrase": forms.PasswordInput(render_value=False),
        }


@admin.register(ExchangeApiKey)
class ExchangeApiKeyAdmin(admin.ModelAdmin):
    form = ExchangeApiKeyAdminForm

    list_display = ("exchange", "label", "api_key_view", "api_secret_view", "api_passphrase_view", "is_enabled")
    list_filter = ("exchange", "is_enabled")
    search_fields = ("exchange__provider", "label")
    readonly_fields = ("api_key_view", "api_secret_view", "api_passphrase_view")
    list_select_related = ("exchange",)

    fieldsets = (
        (None, {"fields": ("exchange", "label", "is_enabled")}),
        (_t("Используемые API ключи"), {"fields": ("api_key_view", "api_secret_view", "api_passphrase_view")}),
        (_t("Обновить API ключи"), {"classes": ("wide", "collapse"), "fields": ("api_key", "api_secret", "api_passphrase")}),
    )