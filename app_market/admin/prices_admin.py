# app_market/admin/prices_admin.py
from decimal import Decimal, InvalidOperation

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _t

from app_market.models.prices.price import PriceL1, VenueType, PriceStatus


@admin.register(PriceL1)
class PriceL1Admin(admin.ModelAdmin):
    list_display = (
        "provider",
        "pair",
        "ask_f",
        "bid_f",
        "last_f",
        "spread_pts",
        "status_badge",
        "age",
        "latency_ms",
    )
    list_filter = (
        ("provider", admin.RelatedOnlyFieldListFilter),
        "venue_type",
        "status",
        # базу/котировку УБРАЛИ из фильтров, чтобы не было тысяч строк
    )
    search_fields = (
        "src_symbol",
        "src_base_code",
        "src_quote_code",
    )
    list_select_related = ("provider", "base_asset", "quote_asset")
    # убираем date_hierarchy по ts_src, чтобы не путать — достаточно age
    ordering = ("-ts_ingest",)
    list_per_page = 100
    save_on_top = True

    # Поля только для чтения (в форме показываем красиво-отформатированные цены)
    readonly_fields = (
        "provider",
        "venue_type",
        "base_asset",
        "quote_asset",
        "src_symbol",
        "src_base_code",
        "src_quote_code",

        # Отформатированные цены (показываем их вместо «сырых» полей)
        "bid_display",
        "ask_display",
        "last_display",
        "mid_display",

        "fee_taker_bps",
        "fee_maker_bps",

        # ts_src не показываем (но age в списке остаётся)
        "ts_ingest",
        "seq",
        "latency_ms",

        "status",
        "quality_note",
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
            # показываем только отформатированные (5 знаков)
            "fields": ("bid_display", "ask_display", "last_display", "mid_display"),
        }),
        (_t("Комиссии провайдера"), {
            "fields": ("fee_taker_bps", "fee_maker_bps"),
        }),
        (_t("Время и последовательность"), {
            # ts_src убрали по твоей просьбе; оставили служебные
            "fields": ("ts_ingest", "seq", "latency_ms"),
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
        # Только коды активов, без сетей и без указания ПЛ
        try:
            return f"{obj.base_asset.asset_code}/{obj.quote_asset.asset_code}"
        except Exception:
            # На всякий случай fallback
            return f"{obj.base_asset_id}/{obj.quote_asset_id}"

    @admin.display(description=_t("Bid"), ordering="bid")
    def bid_f(self, obj: PriceL1) -> str:
        return self._fmt5(obj.bid)

    @admin.display(description=_t("Ask"), ordering="ask")
    def ask_f(self, obj: PriceL1) -> str:
        return self._fmt5(obj.ask)

    @admin.display(description=_t("Last"), ordering="last")
    def last_f(self, obj: PriceL1) -> str:
        return self._fmt5(obj.last)

    @admin.display(description=_t("Mid"))
    def mid_display(self, obj: PriceL1) -> str:
        if obj.bid is None or obj.ask is None:
            return "—"
        try:
            mid = (obj.bid + obj.ask) / Decimal(2)
            return f"{mid:.5f}"
        except InvalidOperation:
            return "—"

    @admin.display(description=_t("Спрэд (пункты)"))
    def spread_pts(self, obj):
        try:
            if obj.bid is None or obj.ask is None:
                return "—"
            # 1 пункт = 1e-5, т.к. цены показываем с 5 знаками
            pts = (obj.ask - obj.bid) * Decimal(10 ** 5)
            # округление к ближайшему целому
            return f"{int(pts.to_integral_value())}"
        except (InvalidOperation, TypeError):
            return "—"

    @admin.display(description=_t("Статус"))
    def status_badge(self, obj: PriceL1):
        color = {
            PriceStatus.OK: "#0a7d2f",
            PriceStatus.STALE: "#b26a00",
            PriceStatus.DEGRADED: "#b00020",
        }.get(obj.status, "#444")
        return format_html(
            '<span style="display:inline-block;padding:2px 8px;border-radius:12px;'
            'background:{bg};color:#fff;font-weight:600;">{txt}</span>',
            bg=color,
            txt=obj.get_status_display(),
        )

    @admin.display(description=_t("Возраст"))
    def age(self, obj: PriceL1) -> str:
        # считаем от ts_src, хотя само поле не показываем
        delta = timezone.now() - obj.ts_src
        total_ms = int(delta.total_seconds() * 1000)
        if total_ms < 1000:
            return f"{total_ms} ms"
        secs = total_ms / 1000
        if secs < 60:
            return f"{secs:.1f} s"
        minutes = int(secs // 60)
        seconds = int(secs % 60)
        return f"{minutes}m {seconds}s"

    # Красиво отрендерить в форме
    @admin.display(description=_t("Bid"))
    def bid_display(self, obj: PriceL1) -> str:
        return self._fmt5(obj.bid)

    @admin.display(description=_t("Ask"))
    def ask_display(self, obj: PriceL1) -> str:
        return self._fmt5(obj.ask)

    @admin.display(description=_t("Last"))
    def last_display(self, obj: PriceL1) -> str:
        return self._fmt5(obj.last)

    def _fmt5(self, val) -> str:
        if val is None:
            return "—"
        try:
            return f"{val:.5f}"
        except Exception:
            return str(val)

    # ---- Права ----
    def has_add_permission(self, request):
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
