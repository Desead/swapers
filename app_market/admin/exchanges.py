from django.contrib import admin
from app_market.models import Exchange, ExchangeApiKey
from django.utils.translation import gettext_lazy as _t

@admin.register(Exchange)
class ExchangeAdmin(admin.ModelAdmin):
    list_display = (
        "name", "is_available",
        "can_receive", "can_send",
        "stablecoin",
        "spot_taker_fee", "spot_maker_fee",
        "futures_taker_fee", "futures_maker_fee",
        "show_prices_on_home",
    )
    list_filter = ("is_available", "can_receive", "can_send", "show_prices_on_home")
    search_fields = ("name", "stablecoin")
    readonly_fields = ("is_available",)  # статус только для просмотра
    fieldsets = (
        (None, {
            "fields": ("name", "is_available"),
        }),
        (_t("Режимы работы"), {
            "fields": (("can_receive", "can_send"),),
        }),
        (_t("Стейблкоин расчётов"), {
            "fields": ("stablecoin",),
        }),
        (_t("Комиссии"), {
            "fields": (
                ("spot_taker_fee", "spot_maker_fee"),
                ("futures_taker_fee", "futures_maker_fee"),
            ),
            "description": _t("Значения в процентах, допускаются отрицательные."),
        }),
        (_t("Отображение"), {
            "fields": ("show_prices_on_home",),
        }),
    )


@admin.register(ExchangeApiKey)
class ExchangeApiKeyAdmin(admin.ModelAdmin):
    list_display = ("exchange", "label", "is_enabled")
    list_filter = ("exchange", "is_enabled")
    search_fields = ("exchange__name", "label")
