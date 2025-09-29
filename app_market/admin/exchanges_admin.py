from django.contrib import admin
from django import forms
from django.utils.translation import gettext_lazy as _t
from app_market.models import Exchange, ExchangeApiKey

@admin.register(Exchange)
class ExchangeAdmin(admin.ModelAdmin):
    save_on_top = True

    list_display = (
        "provider", "exchange_kind", "is_available",
        "can_receive", "can_send","stablecoin",
        "spot_taker_fee", "spot_maker_fee",
        "futures_taker_fee", "futures_maker_fee",
        "show_prices_on_home",
    )
    list_filter = (
        "provider",  "is_available","exchange_kind",
        "can_receive", "can_send", "show_prices_on_home",
    )
    search_fields = ("provider",)
    readonly_fields = ("is_available",)

    fieldsets = (
        (_t("Общее"), {"fields": ("provider", "is_available","webhook_endpoint")}),
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

        (_t("Отображение"), {"fields": ("show_prices_on_home",)}),
    )


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
    search_fields = ("exchange__provider", "label")  # ← раньше было exchange__name
    readonly_fields = ("api_key_view", "api_secret_view", "api_passphrase_view")

    fieldsets = (
        (None, {"fields": ("exchange", "label", "is_enabled")}),
        (_t("Используемые API ключи"), {"fields": ("api_key_view", "api_secret_view", "api_passphrase_view")}),
        (_t("Обновить API ключи"), {"classes": ("wide", "collapse"), "fields": ("api_key", "api_secret", "api_passphrase")}),
    )
