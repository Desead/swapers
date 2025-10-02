from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _t

from app_market.models import CurrencyMap, CurrencyMatchKind


@admin.register(CurrencyMap)
class CurrencyMapAdmin(admin.ModelAdmin):
    save_on_top = True
    ordering = ("exchange", "-priority", "raw_symbol")

    list_display = (
        "exchange",
        "is_active",
        "priority",
        "match_kind",
        "raw_symbol",
        "raw_chain",
        "norm_asset_code",
        "norm_chain_code",
        "updated_at",
    )
    list_filter = (
        "exchange",
        "is_active",
        "match_kind",
    )
    search_fields = (
        "raw_symbol", "raw_chain", "raw_pair",
        "norm_asset_code", "norm_chain_code",
        "pattern",
    )
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        (_t("Назначение"), {
            "fields": ("exchange", "is_active", "priority"),
        }),
        (_t("Сырые обозначения от ПЛ"), {
            "fields": ("raw_symbol", "raw_chain", "raw_pair"),
        }),
        (_t("Нормализация (к нашим кодам)"), {
            "fields": ("norm_asset_code", "norm_chain_code"),
        }),
        (_t("Правило сопоставления (Regex/Split/Custom)"), {
            "classes": ("wide", "collapse"),
            "fields": (
                "match_kind",
                "pattern",
                ("asset_group_idx", "chain_group_idx"),
                "split_delimiters",
                "left_is_asset",
            ),
            "description": _t(
                "EXACT — точное сравнение raw_symbol/raw_chain. "
                "REGEX — используйте pattern и индексы групп для asset/chain. "
                "SPLIT — укажите разделители (например '-/\\') и какая часть — asset."
            ),
        }),
        (_t("Аудит"), {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at"),
        }),
    )

    actions = ["action_activate", "action_deactivate", "action_priority_up", "action_priority_down"]

    class Media:
        js = ("admin/js/collapse.js",)

    @admin.action(description=_t("Активировать выбранные"))
    def action_activate(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, _t("Активировано записей: {}.").format(updated), messages.SUCCESS)

    @admin.action(description=_t("Деактивировать выбранные"))
    def action_deactivate(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, _t("Деактивировано записей: {}.").format(updated), messages.SUCCESS)

    @admin.action(description=_t("Поднять приоритет (+1)"))
    def action_priority_up(self, request, queryset):
        count = 0
        for obj in queryset:
            obj.priority = (obj.priority or 0) + 1
            obj.save(update_fields=["priority"])
            count += 1
        self.message_user(request, _t("Изменён приоритет записей: {}.").format(count), messages.SUCCESS)

    @admin.action(description=_t("Понизить приоритет (−1)"))
    def action_priority_down(self, request, queryset):
        count = 0
        for obj in queryset:
            obj.priority = (obj.priority or 0) - 1
            obj.save(update_fields=["priority"])
            count += 1
        self.message_user(request, _t("Изменён приоритет записей: {}.").format(count), messages.SUCCESS)
