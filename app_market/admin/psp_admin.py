from django.contrib import admin
from django.utils.translation import gettext_lazy as _t
from app_market.models import PaymentProviderProfile

@admin.register(PaymentProviderProfile)
class PaymentProviderProfileAdmin(admin.ModelAdmin):
    list_display = (
        "exchange", "environment", "settlement_currency",
        "fee_deposit_percent", "fee_deposit_fixed",
        "fee_payout_percent", "fee_payout_fixed",
    )
    list_filter = ("environment", "settlement_currency")
    search_fields = ("exchange__name", "merchant_id", "account_email")
    fieldsets = (
        (None, {"fields": ("exchange", "environment")}),
        (_t("Идентификаторы/доступ"), {"fields": ("merchant_id", "account_email")}),
        (_t("Доступ/кабинет"), {"fields": ("api_base_url", "dashboard_url")}),
        (_t("Расчёты и комиссии"), {
            "fields": (
                "settlement_currency",
                ("fee_deposit_percent", "fee_deposit_fixed"),
                ("fee_payout_percent", "fee_payout_fixed"),
            )
        }),
        (_t("Лимиты"), {"fields": (("min_deposit", "max_deposit"),
                                    ("min_payout", "max_payout"))}),
        (_t("Webhooks/идемпотентность"), {"fields": ("webhook_endpoint", "idempotency_window_sec")}),
    )
