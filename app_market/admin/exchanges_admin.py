import json
from django.contrib import admin, messages
from django import forms
from django.utils.translation import gettext_lazy as _t
from django.utils.html import format_html, format_html_join
from app_market.models import Exchange, ExchangeApiKey
from app_market.models.exchange import LiquidityProvider
from app_market.services.health import check_exchange
from app_market.providers import get_adapter, has_adapter
from app_market.services.stats import ensure_initial_stats, collect_exchange_stats


@admin.register(Exchange)
class ExchangeAdmin(admin.ModelAdmin):
    save_on_top = True
    ordering = ("provider",)

    list_display = (
        "provider", "is_available",
        "can_receive", "can_send", "stablecoin",
        "spot_taker_fee", "spot_maker_fee",
        "futures_taker_fee", "futures_maker_fee",
        "show_prices_on_home",
    )
    list_filter = (
        "exchange_kind", "is_available",
        "can_receive", "can_send", "show_prices_on_home",
    )
    search_fields = ("provider",)
    readonly_fields = ("is_available", "exchange_kind", "partner_link", "stats_runs_count", "stats_latest_preview",)

    fieldsets = (
        (_t("Общее"), {
            "fields": (("provider", "is_available"), "exchange_kind", "webhook_endpoint", "partner_link"),
        }),
        (_t("Режимы работы"), {"fields": (("can_receive", "can_send"),)}),
        (_t("Стейблкоин расчётов"), {"fields": ("stablecoin",)}),
        (_t("Торговые комиссии"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("spot_taker_fee", "spot_maker_fee"),
                ("futures_taker_fee", "futures_maker_fee"),
            ),
            "description": _t("Значения в процентах, могут быть отрицательными."),
        }),
        (_t("Комиссии на ввод и вывод"), {
            "description": _t("Если в поле комиссии стоит значение = 0, значит данная комиссия не используется"),
            "classes": ("wide", "collapse"),
            "fields": (
                ("fee_deposit_percent", "fee_withdraw_percent"),
                ("fee_deposit_fixed", "fee_withdraw_fixed"),
                ("fee_deposit_min", "fee_withdraw_min"),
                ("fee_deposit_max", "fee_withdraw_max"),
            )
        }),
        (_t("Статистика "), {  #
            "classes": ("wide", "collapse"),
            "fields": ("stats_runs_count", "stats_latest_preview"),
        }),
        (_t("Отображение"), {
            "description": _t(
                "Цены с этого поставщика ликвидности будут отображаться на главной странице. "
                "Можно одновременно выбирать несколько разных поставщиков, например биржу+банк и т.д."
            ),
            "fields": ("show_prices_on_home",)
        }),
    )

    actions = [
        "action_enable_receive",
        "action_disable_receive",
        "action_enable_send",
        "action_disable_send",
        "action_healthcheck_now",
        "action_collect_stats_now",
        "sync_assets_now",
    ]

    # ---- helpers (view) ----
    def stats_runs_count(self, obj: Exchange):
        cnt = len(obj.stats_history or [])
        return _t("Снимков: %(n)s") % {"n": cnt}

    stats_runs_count.short_description = _t("Всего снимков")

    def stats_latest_preview(self, obj: Exchange):
        hist = obj.stats_history or []
        if not hist:
            return _t("Ещё нет данных.")

        def render_table_card(title: str, snap: dict):
            m = snap.get("markets", {}) or {}
            rows = format_html_join(
                '',
                "<tr><td>{}</td><td><code>{}</code></td><td>{}</td></tr>",
                ((i + 1, (row.get('quote') or ''), row.get('pairs', 0))
                 for i, row in enumerate(list(m.get("quote_popularity") or [])))
            ) or format_html("<tr><td colspan='3'>—</td></tr>")

            return format_html(
                """
                <div style="
                    flex:0 1 calc((100% - 24px)/3);  /* не растём, чтобы три влезали стабильно */
                    box-sizing:border-box;           /* ширина учитывает padding/border */
                    min-width:300px;
                    border:1px solid #ddd;border-radius:6px;padding:10px;">
                  <div style="margin-bottom:6px; line-height:1.2;">
                    <b>{}</b>
                    <div><small>{}</small></div>
                  </div>
                  <table style="width:100%;border-collapse:collapse;">
                    <thead>
                      <tr>
                        <th style="text-align:left;padding-bottom:4px;">#</th>
                        <th style="text-align:left;padding-bottom:4px;">Quote</th>
                        <th style="text-align:left;padding-bottom:4px;">Count</th>
                      </tr>
                    </thead>
                    <tbody>{}</tbody>
                  </table>
                </div>
                """,
                title, snap.get("run_at", "—"), rows,
            )

        cards = [render_table_card(_t("Текущий снимок"), hist[-1])]
        if len(hist) > 1:
            cards.append(render_table_card(_t("Предыдущий снимок"), hist[-2]))
        if len(hist) > 2:
            cards.append(render_table_card(_t("Позапрошлый снимок"), hist[-3]))

        return format_html(
            '<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start;width:100%;">{}</div>',
            format_html_join('', '{}', ((c,) for c in cards))
        )

    stats_latest_preview.short_description = _t("Последний снимок")

    def partner_link(self, obj):
        url = getattr(obj, "partner_url", "") or ""
        if not url:
            return "—"
        label = _t("Перейти на сайт {name}").format(name=obj.get_provider_display())
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', url, label)

    partner_link.short_description = _t("URL")

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        """
        Группируем выпадающий список provider в админке.
        """
        if db_field.name != "provider":
            return super().formfield_for_choice_field(db_field, request, **kwargs)

        field = super().formfield_for_choice_field(db_field, request, **kwargs)
        labels = dict(LiquidityProvider.choices)

        def pick(values):
            return [(v, labels[v]) for v in values if v in labels]

        groups = [
            (_t("Наличные"), pick([
                LiquidityProvider.CASH,
                LiquidityProvider.TWELVEDATA,
                LiquidityProvider.OpExRate,
            ])),
            (_t("Централизованные биржи (CEX)"), pick([
                LiquidityProvider.KUCOIN,
                LiquidityProvider.WHITEBIT,
                LiquidityProvider.BYBIT,
                LiquidityProvider.RAPIRA,
                LiquidityProvider.MEXC,
                # LiquidityProvider.BINANCE,
                # LiquidityProvider.COINBASE_EXCHANGE,
                # LiquidityProvider.UPBIT,
                # LiquidityProvider.BITSTAMP,
                # LiquidityProvider.BINGX,
                # LiquidityProvider.BITFINEX,
                LiquidityProvider.HTX,
                # LiquidityProvider.GATEIO,
                # LiquidityProvider.BITGET,
                # LiquidityProvider.OKX,
                # LiquidityProvider.GEMINI,
                # LiquidityProvider.LBANK,
            ])),
            # (_t("Децентрализованные (DEX)"), pick([
            #     LiquidityProvider.UNISWAP,
            #     LiquidityProvider.PANCAKESWAP,
            # ])),
            # (_t("Обменники (EXCHANGER)"), pick([
            #     LiquidityProvider.CHANGENOW,
            #     LiquidityProvider.CHANGELLY,
            #     LiquidityProvider.FIXEDFLOAT,
            #     LiquidityProvider.QUICKEX,
            # ])),
            # (_t("Кошельки (WALLET)"), pick([
            #     LiquidityProvider.WESTWALLET,
            #     LiquidityProvider.TRUSTWALLET,
            #     LiquidityProvider.TRONWALLET,
            #     LiquidityProvider.ANTARCTICWALLET,
            #     LiquidityProvider.TELEGRAM_WALLET,
            # ])),
            # (_t("Банки (BANK)"), pick([
            #     LiquidityProvider.SBERBANK,
            #     LiquidityProvider.ALFABANK,
            #     LiquidityProvider.VTB,
            #     LiquidityProvider.TBANK,
            # ])),
            # (_t("Ноды (NODE)"), pick([
            #     LiquidityProvider.BTC_NODE,
            #     LiquidityProvider.XMR_NODE,
            #     LiquidityProvider.USDT_NODE,
            #     LiquidityProvider.USDC_NODE,
            #     LiquidityProvider.DASH_NODE,
            # ])),
            # (_t("Платёжные системы (PSP)"), pick([
            #     LiquidityProvider.PAYPAL,
            #     LiquidityProvider.ADVCASH,
            #     LiquidityProvider.FIREKASSA,
            #     LiquidityProvider.APIRONE,
            # ])),
        ]

        field.choices = [g for g in groups if g[1]]
        return field

    @admin.action(description=_t("Включить приём средств"))
    def action_enable_receive(self, request, queryset):
        updated = queryset.update(can_receive=True)
        self.message_user(request, _t("Обновлено записей: {}.").format(updated), messages.SUCCESS)

    @admin.action(description=_t("Выключить приём средств"))
    def action_disable_receive(self, request, queryset):
        updated = queryset.update(can_receive=False)
        self.message_user(request, _t("Обновлено записей: {}.").format(updated), messages.SUCCESS)

    @admin.action(description=_t("Включить вывод средств"))
    def action_enable_send(self, request, queryset):
        updated = queryset.update(can_send=True)
        self.message_user(request, _t("Обновлено записей: {}.").format(updated), messages.SUCCESS)

    @admin.action(description=_t("Выключить вывод средств"))
    def action_disable_send(self, request, queryset):
        updated = queryset.update(can_send=False)
        self.message_user(request, _t("Обновлено записей: {}.").format(updated), messages.SUCCESS)

    @admin.action(description=_t("Проверить доступность"))
    def action_healthcheck_now(self, request, queryset):
        ok = down = 0
        for ex in queryset:
            res = check_exchange(ex, persist=True)
            if res.available:
                ok += 1
            else:
                down += 1
        msg = _t("Готово: доступно={} недоступно={}.").format(ok, down)
        level = messages.SUCCESS if down == 0 else messages.WARNING
        self.message_user(request, msg + " " + _t("Подробности см. в 'История доступности'."), level)

    @admin.action(description=_t("Собрать статистику сейчас"))
    def action_collect_stats_now(self, request, queryset):
        ok = err = 0
        for ex in queryset.only("id", "provider", "exchange_kind"):
            try:
                collect_exchange_stats(ex, timeout=25)
                # Лаконичное сообщение без цифр:
                messages.success(request, _t("Статистика по %(ex)s собрана.") % {"ex": ex})
                ok += 1
            except Exception as e:
                messages.error(request, f"{ex}: ошибка сбора статистики: {e}")
                err += 1
        if err:
            messages.warning(request, _t("Готово с ошибками: %(n)s") % {"n": err})
        else:
            messages.info(request, _t("Готово: %(n)s провайдер(ов)") % {"n": ok})

    @admin.action(description=_t("Синхронизировать активы (загрузить монеты) сейчас"))
    def sync_assets_now(self, request, queryset):
        """
        Админ-экшен: для выделенных ПЛ запускает загрузку монет через адаптеры.
        Использует тот же pipeline, что и management-команда.
        """
        total_processed = total_created = total_updated = total_skipped = total_disabled = 0
        errors = 0
        # Берём только нужные поля; поля 'name' у модели нет.
        for ex in queryset.only("id", "provider"):
            code = ex.provider
            title = str(ex)

            if not has_adapter(code):
                messages.warning(request, f"{title}: адаптер не найден — пропущено.")
                continue

            adapter = get_adapter(code)
            if not hasattr(adapter, "sync_assets"):
                messages.error(request, f"{title}: некорректный адаптер (нет метода sync_assets).")
                errors += 1
                continue

            try:
                stats = adapter.sync_assets(
                    exchange=ex,
                    timeout=15,
                    reconcile=False,
                    verbose=False,  # в админку не спамим помонетно
                )
                p = getattr(stats, "processed", 0)
                c = getattr(stats, "created", 0)
                u = getattr(stats, "updated", 0)
                s = getattr(stats, "skipped", 0)
                d = getattr(stats, "disabled", 0)

                total_processed += p
                total_created += c
                total_updated += u
                total_skipped += s
                total_disabled += d

                messages.success(
                    request,
                    f"{title}: processed={p}, created={c}, updated={u}, skipped={s}, disabled={d}"
                )
                # первый автозапуск статистики (только если её ещё нет)
                if ensure_initial_stats(ex, timeout=20):
                    messages.info(request, f"{title}: первичная статистика собрана.")
            except Exception as e:
                errors += 1
                messages.error(request, f"{title}: ошибка синхронизации: {e}")

        if errors == 0:
            messages.info(
                request,
                f"Готово. Итого: processed={total_processed}, created={total_created}, "
                f"updated={total_updated}, skipped={total_skipped}, disabled={total_disabled}"
            )
        else:
            messages.warning(
                request,
                f"Завершено с ошибками: {errors}. "
                f"Итого: processed={total_processed}, created={total_created}, "
                f"updated={total_updated}, skipped={total_skipped}, disabled={total_disabled}"
            )


class ExchangeApiKeyAdminForm(forms.ModelForm):
    """
    Безопасное обновление ключей:
    - если поля паролей оставить пустыми — НЕ перезаписываем существующие значения;
    - можно намеренно очистить поле через чекбокс "clear_*".
    """
    # чекбоксы «очистить»
    clear_api_key = forms.BooleanField(required=False, label=_t("Очистить API Key"))
    clear_api_secret = forms.BooleanField(required=False, label=_t("Очистить API Secret"))
    clear_api_passphrase = forms.BooleanField(required=False, label=_t("Очистить Passphrase"))
    clear_api_broker = forms.BooleanField(required=False, label=_t("Очистить Broker Key"))

    class Meta:
        model = ExchangeApiKey
        fields = (
            "exchange", "label", "is_enabled",
            # readonly views рендерятся из Admin, в форму их не включаем
            "api_key", "api_secret", "api_passphrase", "api_broker",
            "clear_api_key", "clear_api_secret", "clear_api_passphrase", "clear_api_broker",
        )
        widgets = {
            "api_key": forms.PasswordInput(render_value=False),
            "api_secret": forms.PasswordInput(render_value=False),
            "api_passphrase": forms.PasswordInput(render_value=False),
            "api_broker": forms.PasswordInput(render_value=False),
        }

    def clean(self):
        cd = super().clean()
        inst = self.instance

        # Обработка очистки/обновления каждого поля
        for field, clear_field in (
                ("api_key", "clear_api_key"),
                ("api_secret", "clear_api_secret"),
                ("api_passphrase", "clear_api_passphrase"),
                ("api_broker", "clear_api_broker"),
        ):
            want_clear = cd.get(clear_field)
            new_val = cd.get(field)

            if want_clear:
                cd[field] = ""  # очистим значение
            else:
                # Если в поле пусто — оставляем старое
                if not new_val:
                    cd[field] = getattr(inst, field)

        return cd


@admin.register(ExchangeApiKey)
class ExchangeApiKeyAdmin(admin.ModelAdmin):
    save_on_top = True
    form = ExchangeApiKeyAdminForm

    list_display = ("exchange", "is_enabled", "label", "api_key_view", "api_secret_view", "api_passphrase_view", "api_broker_view",)
    list_filter = ("exchange", "is_enabled")
    search_fields = ("exchange__provider", "label")
    readonly_fields = ("api_key_view", "api_secret_view", "api_passphrase_view", "api_broker_view")
    list_select_related = ("exchange",)

    fieldsets = (
        (_t("Общее"), {"fields": (("exchange", "label"), "is_enabled")}),
        (_t("Текущие API ключи"), {"fields": ("api_key_view", "api_secret_view", "api_passphrase_view", "api_broker_view")}),
        (_t("Обновить API ключи"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("api_key", "clear_api_key"),
                ("api_secret", "clear_api_secret"),
                ("api_passphrase", "clear_api_passphrase"),
                ("api_broker", "clear_api_broker"),
            ),
            "description": _t("Оставьте поля пустыми, чтобы не менять ключи. "
                              "Поставьте галочку «Очистить», чтобы удалить значение."),
        }),
    )
