from decimal import Decimal, InvalidOperation

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _t

from app_market.models.price import VenueType, PriceStatus, PriceL1


@admin.register(PriceL1)
class PriceL1Admin(admin.ModelAdmin):
    list_display = (
        "provider",
        "venue_type",
        "pair",
        "bid",
        "ask",
        "spread_pct",
        "last",
        "status_badge",
        "ts_src",
        "age",
        "latency_ms",
    )
    list_filter = (
        ("provider", admin.RelatedOnlyFieldListFilter),
        "venue_type",
        "status",
        ("base_asset", admin.RelatedOnlyFieldListFilter),
        ("quote_asset", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        "src_symbol",
        "src_base_code",
        "src_quote_code",
    )
    list_select_related = ("provider", "base_asset", "quote_asset")
    date_hierarchy = "ts_src"
    ordering = ("-ts_src",)
    list_per_page = 100
    save_on_top = True

    # Поля только для чтения (разрешаем править статус и комментарий качества)
    readonly_fields = (
        "provider",
        "venue_type",
        "base_asset",
        "quote_asset",
        "src_symbol",
        "src_base_code",
        "src_quote_code",
        "bid",
        "ask",
        "last",
        "mid_display",
        "fee_taker_bps",
        "fee_maker_bps",
        "ts_src",
        "ts_ingest",
        "seq",
        "latency_ms",
        "extras",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (_t("Источник"), {
            "fields": (
                "provider", "venue_type",
                "src_symbol", "src_base_code", "src_quote_code",
            )
        }),
        (_t("Пара"), {
            "fields": ("base_asset", "quote_asset"),
        }),
        (_t("Цены (L1)"), {
            "fields": ("bid", "ask", "last", "mid_display"),
        }),
        (_t("Комиссии провайдера"), {
            "fields": ("fee_taker_bps", "fee_maker_bps"),
        }),
        (_t("Время и последовательность"), {
            "fields": ("ts_src", "ts_ingest", "seq", "latency_ms"),
        }),
        (_t("Качество данных"), {
            "fields": ("status", "quality_note"),
        }),
        (_t("Дополнительно"), {
            "classes": ("collapse",),
            "fields": ("extras", "created_at", "updated_at"),
        }),
    )

    actions = ("mark_ok", "mark_stale", "mark_degraded")

    # ---- Представление/форматирование ----

    @admin.display(description=_t("Пара"))
    def pair(self, obj: PriceL1) -> str:
        return f"{obj.base_asset}/{obj.quote_asset}"

    @admin.display(description=_t("Спрэд, %"))
    def spread_pct(self, obj: PriceL1):
        try:
            if obj.bid is None or obj.ask is None:
                return "—"
            mid = (obj.bid + obj.ask) / Decimal(2)
            if mid <= 0:
                return "—"
            pct = (obj.ask - obj.bid) / mid * Decimal(100)
            return f"{pct:.4f}"
        except (InvalidOperation, ZeroDivisionError):
            return "—"

    @admin.display(description=_t("Статус"))
    def status_badge(self, obj: PriceL1):
        color = {
            PriceStatus.OK: "#0a7d2f",  # зелёный
            PriceStatus.STALE: "#b26a00",  # янтарный
            PriceStatus.DEGRADED: "#b00020",  # красный
        }.get(obj.status, "#444")
        return format_html(
            '<span style="display:inline-block;padding:2px 8px;border-radius:12px;'
            'background:{bg};color:#fff;font-weight:600;">{txt}</span>',
            bg=color,
            txt=obj.get_status_display(),
        )

    @admin.display(description=_t("Возраст"))
    def age(self, obj: PriceL1) -> str:
        delta = timezone.now() - obj.ts_src
        total_ms = int(delta.total_seconds() * 1000)
        if total_ms < 1000:
            return f"{total_ms} ms"
        # до минуты показываем с секундами, далее — человекочитаемо
        secs = total_ms / 1000
        if secs < 60:
            return f"{secs:.1f} s"
        minutes = int(secs // 60)
        seconds = int(secs % 60)
        return f"{minutes}m {seconds}s"

    @admin.display(description=_t("Mid"))
    def mid_display(self, obj: PriceL1):
        if obj.bid is None or obj.ask is None:
            return "—"
        try:
            mid = (obj.bid + obj.ask) / Decimal(2)
            return f"{mid:.10f}"
        except InvalidOperation:
            return "—"

    # ---- Права ----
    def has_add_permission(self, request):
        # Эти записи приходят из коннекторов; вручную не создаём
        return False

    # ---- Actions ----
    @admin.action(description=_t("Пометить как OK"))
    def mark_ok(self, request, queryset):
        updated = queryset.update(status=PriceStatus.OK, quality_note=_t("Помечено вручную из админки"))
        self.message_user(request, _t(f"Обновлено записей: {updated}"))

    @admin.action(description=_t("Пометить как STALE"))
    def mark_stale(self, request, queryset):
        updated = queryset.update(status=PriceStatus.STALE, quality_note=_t("Помечено вручную как устаревшее"))
        self.message_user(request, _t(f"Обновлено записей: {updated}"))

    @admin.action(description=_t("Пометить как DEGRADED"))
    def mark_degraded(self, request, queryset):
        updated = queryset.update(status=PriceStatus.DEGRADED, quality_note=_t("Помечено вручную как деградация"))
        self.message_user(request, _t(f"Обновлено записей: {updated}"))
