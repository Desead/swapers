from django.contrib import admin
from django.utils.translation import gettext_lazy as _t
from app_market.models import ExchangeAvailabilityLog


@admin.register(ExchangeAvailabilityLog)
class ExchangeAvailabilityLogAdmin(admin.ModelAdmin):
    list_display = ("exchange", "created_at", "available", "code", "latency_ms", "detail")
    list_filter = ("available", "code", "exchange")
    search_fields = ("exchange__provider", "code", "detail")
    date_hierarchy = "created_at"
    readonly_fields = ("exchange", "created_at", "available", "code", "latency_ms", "detail")
    ordering = ("-created_at",)
    list_per_page = 50  # ← разумный дефолт

