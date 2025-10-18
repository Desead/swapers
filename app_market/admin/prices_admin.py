from decimal import Decimal, InvalidOperation

from django.contrib import admin
from django.utils import timezone
from django.utils.translation import gettext_lazy as _t

from app_market.models.price import PriceL1


@admin.register(PriceL1)
class PriceL1Admin(admin.ModelAdmin):
    list_display = (
        "provider",
        "pair",
        "bid_f",
        "ask_f",
        "last_f",
        "age",
        "latency_ms",
    )
    list_filter = (
        "provider",
    )
    search_fields = (
        # "src_symbol",
        "src_base_code",
        "src_quote_code",
    )
    list_select_related = ("provider",)
    ordering = ("-ts_ingest", "-id")
    list_per_page = 100
    save_on_top = True

    # Поля только для чтения (редактирование не предполагается)
    readonly_fields = (
        "provider",
        "src_symbol",
        "src_base_code",
        "src_quote_code",

        # Отформатированные цены (5 знаков)
        "bid_display",
        "ask_display",
        "last_display",
        "mid_display",

        "fee_taker_bps",
        "fee_maker_bps",
        "fee_source",

        # ts_src сознательно не показываем (оставляем только age в списке)
        "ts_ingest",
        "seq",
        "latency_ms",

        "extras",
        "created_at",
        "updated_at",

        # Волатильность
        "wv", "dv", "hv", "mv",
    )

    fieldsets = (
        (_t("Источник"), {
            "fields": (
                "provider",
                "src_symbol",
                ("src_base_code", "src_quote_code"),
            )
        }),
        (_t("Цены (L1)"), {
            "classes": ("collapse",),
            "fields": (("bid_display", "ask_display",), ("last_display", "mid_display",),),
        }),
        (_t("Волатильность (WV/DV/HV/MV)"), {
            "classes": ("collapse",),
            "fields": (("wv", "dv", "hv", "mv"),),
        }),
        (_t("Комиссии"), {
            "classes": ("collapse",),
            "fields": ("fee_taker_bps", "fee_maker_bps", "fee_source"),
        }),
        (_t("Время и последовательность"), {
            "classes": ("collapse",),
            # ts_src не показываем; в списке есть age
            "fields": ("ts_ingest", "seq", "latency_ms"),
        }),
        (_t("Дополнительно"), {
            "classes": ("collapse",),
            "fields": ("extras", "created_at", "updated_at"),
        }),
    )

    # ----- Представление / форматирование -----

    @admin.display(description=_t("Пара"))
    def pair(self, obj: PriceL1) -> str:
        # Только коды у ПЛ, без сетей и без указания ПЛ
        return f"{obj.src_base_code}/{obj.src_quote_code}"

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

    @admin.display(description=_t("Возраст"))
    def age(self, obj: PriceL1) -> str:
        # считаем от времени источника, само поле не показываем
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

    # Отформатированные поля для формы
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

    # ----- Права -----
    def has_add_permission(self, request):
        return False
