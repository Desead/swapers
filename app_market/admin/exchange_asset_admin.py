from decimal import Decimal
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _t
from django import forms
from django.db import models

from app_market.models import ExchangeAsset


# --- форматтер для Decimal без экспоненты ---
def _fmt_decimal(v):
    if isinstance(v, Decimal):
        s = format(v, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s or "0"
    return v


class ExchangeAssetForm(forms.ModelForm):
    class Meta:
        model = ExchangeAsset
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Человекочитаемое отображение Decimal-полей (без 0E-10)
        for name, field in self.fields.items():
            if isinstance(field, forms.DecimalField) and name in self.initial:
                self.initial[name] = _fmt_decimal(self.initial[name])


# --- кастомные фильтры «эффективной доступности» (D&AD&exchange.is_available) ---
class DepositOpenFilter(admin.SimpleListFilter):
    title = _t("Ввод")
    parameter_name = "deposit_open"

    def lookups(self, request, model_admin):
        return [("yes", _t("Да")), ("no", _t("Нет"))]

    def queryset(self, request, queryset):
        val = self.value()
        if val == "yes":
            return queryset.filter(D=True, AD=True, exchange__is_available=True, exchange__can_receive=True)
        if val == "no":
            return queryset.exclude(D=True, AD=True, exchange__is_available=True, exchange__can_receive=True)
        return queryset


class WithdrawOpenFilter(admin.SimpleListFilter):
    title = _t("Вывод")
    parameter_name = "withdraw_open"

    def lookups(self, request, model_admin):
        return [("yes", _t("Да")), ("no", _t("Нет"))]

    def queryset(self, request, queryset):
        val = self.value()
        if val == "yes":
            return queryset.filter(W=True, AW=True, exchange__is_available=True, exchange__can_send=True)
        if val == "no":
            return queryset.exclude(W=True, AW=True, exchange__is_available=True, exchange__can_send=True)
        return queryset


@admin.register(ExchangeAsset)
class ExchangeAssetAdmin(admin.ModelAdmin):
    form = ExchangeAssetForm
    save_on_top = True
    ordering = ("exchange", "asset_code", "chain_code")

    list_display = (
        "exchange",
        "asset_code",
        "chain_code",
        "asset_kind",
        "confirmations_view",  # ← новое поле-колонка "2/3"
        "deposit_open",
        "withdraw_open",
        "is_stablecoin",
        "reserve_current",
        "requires_memo",
        "last_synced_at",
    )
    list_display_links = ("exchange", "asset_code", "chain_code")
    list_filter = (
        "exchange",
        "asset_kind",
        "is_stablecoin",
        "requires_memo",
        DepositOpenFilter,
        WithdrawOpenFilter,
    )
    search_fields = (
        "asset_code",
        "asset_name",
        "chain_code",
        "chain_display",
        "provider_symbol",
        "provider_chain",
    )

    readonly_fields = (
        "AD",
        "AW",
        "confirmations_view",  # ← показываем «2/3» в карточке
        "deposit_open",
        "withdraw_open",
        "created_at",
        "updated_at",
        "last_synced_at",
        "icon_preview",
    )

    fieldsets = (
        (_t("Идентификация"), {
            "fields": (
                "exchange",
                ("asset_code", "asset_name"),
                ("chain_code", "chain_display"),
                "asset_kind", "is_stablecoin", "requires_memo",
            )
        }),
        (_t("Доступность"), {
            "fields": (
                ("D", "AD", "deposit_open"),
                ("W", "AW", "withdraw_open"),
            ),
            "description": _t("Итоговые флаги = (ручной × авто × доступность ПЛ). Ввод: D+AD. Вывод: W+AW."),
        }),
        (_t("Подтверждения в сети"), {
            "fields": (("confirmations_deposit", "confirmations_withdraw"),),
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
            "fields": (("nominal", "amount_precision", "amount_precision_display"), ("reserve_current", "reserve_min", "reserve_max")),
        }),
        (_t("Иконка"), {"classes": ("collapse",), "fields": ("icon_file", "icon_url", "icon_preview")}),
        (_t("Служебное"), {"classes": ("wide", "collapse"), "fields": ("provider_symbol", "provider_chain", "status_note", "raw_metadata", "last_synced_at")}),
        (_t("Аудит"), {"classes": ("collapse",), "fields": ("created_at", "updated_at")}),
    )

    formfield_overrides = {
        models.DecimalField: {
            "widget": forms.NumberInput(attrs={"style": "min-width: 8.5em"})
        },
        models.IntegerField: {
            "widget": forms.NumberInput(attrs={"style": "min-width: 8.5em"})
        },
    }

    # --- helpers / рендеринг ---
    def icon_preview(self, obj: ExchangeAsset):
        url = obj.icon_url or (getattr(obj.icon_file, "url", "") or "")
        return "—" if not url else format_html(
            '<img src="{}" style="max-width:128px;max-height:128px;border-radius:8px;" />', url
        )

    icon_preview.short_description = _t("Превью")

    def deposits_tuple(self, obj: ExchangeAsset) -> tuple[int, int]:
        dep = int(getattr(obj, "confirmations_deposit", 0) or 0)
        wdr = int(getattr(obj, "confirmations_withdraw", 0) or 0)
        # на всякий случай поддержим правило: withdraw >= deposit
        if wdr < dep:
            wdr = dep
        return dep, wdr

    def confirmations_view(self, obj: ExchangeAsset) -> str:
        dep, wdr = self.deposits_tuple(obj)
        return f"{dep}/{wdr}"

    confirmations_view.short_description = _t("Подтверждения")

    def deposit_open(self, obj: ExchangeAsset) -> bool:
        return obj.deposit_open

    deposit_open.boolean = True
    deposit_open.short_description = _t("Ввод")

    def withdraw_open(self, obj: ExchangeAsset) -> bool:
        return obj.withdraw_open

    withdraw_open.boolean = True
    withdraw_open.short_description = _t("Вывод")
