from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _t

from app_market.models import ExchangeAsset


# --- кастомные фильтры «эффективной доступности» (D&AD&exchange.is_available) ---

class DepositOpenFilter(admin.SimpleListFilter):
    title = _t("Ввод открыт (эффективно)")
    parameter_name = "deposit_open"

    def lookups(self, request, model_admin):
        return [("yes", _t("Да")), ("no", _t("Нет"))]

    def queryset(self, request, queryset):
        val = self.value()
        if val == "yes":
            return queryset.filter(D=True, AD=True, exchange__is_available=True)
        if val == "no":
            return queryset.exclude(D=True, AD=True, exchange__is_available=True)
        return queryset


class WithdrawOpenFilter(admin.SimpleListFilter):
    title = _t("Вывод открыт (эффективно)")
    parameter_name = "withdraw_open"

    def lookups(self, request, model_admin):
        return [("yes", _t("Да")), ("no", _t("Нет"))]

    def queryset(self, request, queryset):
        val = self.value()
        if val == "yes":
            return queryset.filter(W=True, AW=True, exchange__is_available=True)
        if val == "no":
            return queryset.exclude(W=True, AW=True, exchange__is_available=True)
        return queryset


@admin.register(ExchangeAsset)
class ExchangeAssetAdmin(admin.ModelAdmin):
    save_on_top = True
    ordering = ("exchange", "asset_code", "chain_code")

    list_display = (
        "icon_small",
        "exchange",
        "asset_code",
        "chain_code",
        "asset_kind",
        "D", "AD", "deposit_open",
        "W", "AW", "withdraw_open",
        "is_stablecoin",
        "reserve_current",
        "api_slug",
        "last_synced_at",
    )
    list_filter = (
        "exchange",
        "asset_kind",
        "is_stablecoin",
        "D", "W", "AD", "AW",
        DepositOpenFilter,
        WithdrawOpenFilter,
        "chain_code",
    )
    search_fields = (
        "asset_code", "asset_name",
        "chain_code", "chain_display",
        "provider_symbol", "provider_chain",
        "api_slug",
    )

    # AD/AW и вычисляемые поля – только чтение
    readonly_fields = (
        "AD", "AW",
        "deposit_open", "withdraw_open",
        "created_at", "updated_at", "last_synced_at",
        "icon_preview",
    )

    fieldsets = (
        (_t("Идентификация"), {
            "fields": (
                "exchange",
                ("asset_code", "asset_name"),
                ("chain_code", "chain_display"),
                "asset_kind",
                "api_slug",
                "is_stablecoin",
            )
        }),
        (_t("Доступность"), {
            "fields": (
                ("D", "AD", "deposit_open"),
                ("W", "AW", "withdraw_open"),
            ),
            "description": _t(
                "Итоговые флаги открытости считаются как логическое И: "
                "ручной × авто × доступность ПЛ. "
                "Ввод: D (ручной), AD (авто), итого = «Ввод открыт». "
                "Вывод: W (ручной), AW (авто), итого = «Вывод открыт»."
            ),
        }),
        (_t("Подтверждения в сети"), {
            "fields": ("confirmations_deposit", "confirmations_withdraw"),
        }),
        (_t("Комиссии и лимиты — ВВОД"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("deposit_fee_percent", "deposit_fee_fixed"),
                ("deposit_min", "deposit_max"),
                ("deposit_min_usdt", "deposit_max_usdt"),
            ),
            "description": _t("0 означает, что параметр не используется."),
        }),
        (_t("Комиссии и лимиты — ВЫВОД"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("withdraw_fee_percent", "withdraw_fee_fixed"),
                ("withdraw_min", "withdraw_max"),
                ("withdraw_min_usdt", "withdraw_max_usdt"),
            ),
            "description": _t("0 означает, что параметр не используется."),
        }),
        (_t("Номинал, точность и резервы"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("amount_precision", "nominal"),
                ("reserve_current", "reserve_min", "reserve_max"),
            ),
            "description": _t(
                "Автополитики по резервам должны менять флаги AD/AW во внешнем сервисе, а не D/W."
            ),
        }),
        (_t("Иконка"), {
            "classes": ("collapse",),
            "fields": ("icon_file", "icon_url", "icon_preview"),
        }),
        (_t("Служебное"), {
            "classes": ("wide", "collapse"),
            "fields": ("provider_symbol", "provider_chain", "status_note", "raw_metadata", "last_synced_at"),
        }),
        (_t("Аудит"), {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at"),
        }),
    )

    actions = [
        "action_enable_deposit",
        "action_disable_deposit",
        "action_enable_withdraw",
        "action_disable_withdraw",
        "action_mark_stablecoin",
        "action_unmark_stablecoin",
    ]

    class Media:
        js = ("admin/js/collapse.js",)

    # --- отображение/вспомогательные методы ---

    def icon_small(self, obj: ExchangeAsset):
        url = ""
        if obj.icon_url:
            url = obj.icon_url
        elif obj.icon_file:
            try:
                url = obj.icon_file.url
            except Exception:
                url = ""
        if not url:
            return "—"
        return format_html('<img src="{}" alt="" style="width:22px;height:22px;border-radius:4px;" />', url)
    icon_small.short_description = _t("Иконка")

    def icon_preview(self, obj: ExchangeAsset):
        url = ""
        if obj.icon_url:
            url = obj.icon_url
        elif obj.icon_file:
            try:
                url = obj.icon_file.url
            except Exception:
                url = ""
        if not url:
            return "—"
        return format_html('<img src="{}" alt="" style="max-width:128px;max-height:128px;border-radius:8px;" />', url)
    icon_preview.short_description = _t("Превью")

    # Вычисляемые (readonly) выводим через свойства модели
    def deposit_open(self, obj: ExchangeAsset) -> bool:  # noqa: F811 (перекрывает имя поля в readonly_fields)
        return obj.deposit_open
    deposit_open.boolean = True
    deposit_open.short_description = _t("Ввод открыт")

    def withdraw_open(self, obj: ExchangeAsset) -> bool:  # noqa: F811
        return obj.withdraw_open
    withdraw_open.boolean = True
    withdraw_open.short_description = _t("Вывод открыт")

    # --- actions ---

    @admin.action(description=_t("Включить приём (D=True)"))
    def action_enable_deposit(self, request, queryset):
        updated = queryset.update(D=True)
        self.message_user(request, _t("Обновлено записей: {}.").format(updated), messages.SUCCESS)

    @admin.action(description=_t("Выключить приём (D=False)"))
    def action_disable_deposit(self, request, queryset):
        updated = queryset.update(D=False)
        self.message_user(request, _t("Обновлено записей: {}.").format(updated), messages.SUCCESS)

    @admin.action(description=_t("Включить отдачу (W=True)"))
    def action_enable_withdraw(self, request, queryset):
        updated = queryset.update(W=True)
        self.message_user(request, _t("Обновлено записей: {}.").format(updated), messages.SUCCESS)

    @admin.action(description=_t("Выключить отдачу (W=False)"))
    def action_disable_withdraw(self, request, queryset):
        updated = queryset.update(W=False)
        self.message_user(request, _t("Обновлено записей: {}.").format(updated), messages.SUCCESS)

    @admin.action(description=_t("Пометить как стейблкоин"))
    def action_mark_stablecoin(self, request, queryset):
        updated = queryset.update(is_stablecoin=True)
        self.message_user(request, _t("Обновлено записей: {}.").format(updated), messages.SUCCESS)

    @admin.action(description=_t("Снять пометку стейблкоина"))
    def action_unmark_stablecoin(self, request, queryset):
        updated = queryset.update(is_stablecoin=False)
        self.message_user(request, _t("Обновлено записей: {}.").format(updated), messages.SUCCESS)
