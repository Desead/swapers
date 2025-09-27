from django.contrib import admin
from django import forms
from app_market.models import Exchange, ExchangeApiKey
from django.utils.translation import gettext_lazy as _t

@admin.register(Exchange)
class ExchangeAdmin(admin.ModelAdmin):
    save_on_top = True
    list_display = (
        "name", "exchange_kind", "is_available",
        "can_receive", "can_send",
        "stablecoin",
        "spot_taker_fee", "spot_maker_fee",
        "futures_taker_fee", "futures_maker_fee",
        "show_prices_on_home",
    )
    list_filter = ("exchange_kind", "is_available", "can_receive", "can_send", "show_prices_on_home")
    search_fields = ("name", "stablecoin")
    readonly_fields = ("is_available",)
    fieldsets = (
        (None, {"fields": ("name", "exchange_kind", "is_available")}),
        (_t("Режимы работы"), {"fields": ("can_receive", "can_send")}),
        (_t("Стейблкоин расчётов"), {"fields": ("stablecoin",)}),
        (_t("Комиссии"), {
            "fields": (
                ("spot_taker_fee", "spot_maker_fee"),
                ("futures_taker_fee", "futures_maker_fee"),
            ),
            "description": _t("Значения в процентах, допускаются отрицательные."),
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
    search_fields = ("exchange__name", "label")
    readonly_fields = ("api_key_view", "api_secret_view", "api_passphrase_view")

    fieldsets = (
        (None, {
            "fields": ("exchange", "label", "is_enabled"),
        }),
        (_t("Используемые API ключи"), {
            "fields": ("api_key_view", "api_secret_view", "api_passphrase_view"),
        }),
        (_t("Обновить API ключи"), {
            "classes": ("wide", "collapse"),
            "fields": ("api_key", "api_secret", "api_passphrase"),
        }),
    )
