from __future__ import annotations

from django.contrib import admin
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.conf import settings

from .models import SiteSetup
from .utils.telegram import send_telegram_message
from .utils.audit import diff_sitesetup, format_telegram_message


class SiteSetupAdmin(admin.ModelAdmin):
    save_on_top = True

    readonly_fields = ("updated_at", "og_image_width", "og_image_height",)

    # ПЕРВЫЙ блок раскрыт, остальные свёрнуты
    fieldsets = (
        ("Главная страница", {
            "classes": ("wide",),
            "fields": ("main_h1", "main_subtitle", ("domain", "domain_view"), "maintenance_mode",),
        }),

        ("Брендинг", {
            "classes": ("wide", "collapse"),
            "fields": (("logo", "favicon"),),
        }),
        ("Комиссии и списки стейблкоинов", {
            "classes": ("wide", "collapse"),
            "fields": (("stablecoins", "fee_percent",),),
        }),

        ("Интеграции: XML, <head>, Telegram", {
            "classes": ("wide", "collapse"),
            "fields": ("head_inject_html", "xml_export_path", ("telegram_bot_token", "telegram_chat_id"),),
        }),

        ("График работы (UTC)", {
            "classes": ("wide", "collapse"),
            "fields": (
                ("open_time_mon", "close_time_mon"),
                ("open_time_tue", "close_time_tue"),
                ("open_time_wed", "close_time_wed"),
                ("open_time_thu", "close_time_thu"),
                ("open_time_fri", "close_time_fri"),
                ("open_time_sat", "close_time_sat"),
                ("open_time_sun", "close_time_sun"),
            ),
        }),
        ("Контакты и соцсети", {
            "classes": ("wide", "collapse"),
            "fields": (
                "social_tg",
                "social_vk", "social_dzen",
                "social_youtube", "social_rutube",
                "social_instagram", "contact_telegram",
                ("contact_label_clients", "contact_email_clients",),
                ("contact_label_partners", "contact_email_partners",),
                ("contact_label_general", "contact_email_general",),
            ),
        }),
        # === Twitter Cards ===
        ("Twitter Cards", {
            "classes": ("wide", "collapse"),
            "fields": (
                "twitter_cards_enabled",
                "twitter_card_type",
                ("twitter_site", "twitter_creator"),
                ("twitter_image",),
            ),
        }),

        ("SEO / robots.txt", {
            "classes": ("wide", "collapse"),
            "fields": (
                "block_indexing",
                "robots_txt",
                "seo_default_title",
                "seo_default_description",
                "seo_default_keywords",
            ),
        }),

        # === Open Graph ===
        ("Open Graph", {
            "classes": ("wide", "collapse"),
            "fields": (
                "og_enabled",
                ("og_type_default", "og_locale_default"),
                ("og_title",),
                ("og_description",),
                ("og_image", "og_image_alt"),
                ("og_image_width", "og_image_height"),
                ("og_locale_alternates",),
            ),
        }),

        # === Canonical и hreflang ===
        ("Canonical и hreflang", {
            "classes": ("wide", "collapse"),
            "fields": (
                "use_https_in_meta",
                "hreflang_enabled",
                "hreflang_xdefault",
            ),
        }),

        # === Structured Data (JSON-LD) ===
        ("Структурированные данные (JSON-LD)", {
            "classes": ("wide", "collapse"),
            "fields": (
                "jsonld_enabled",
                ("jsonld_organization", "jsonld_website",),
            ),
        }),

        ("Почтовые настройки", {
            "classes": ("wide", "collapse"),
            "fields": (
                ("email_host", "email_port"),
                ("email_host_user", "email_host_password"),
                ("email_from"),
                "email_use_tls", "email_use_ssl",
            ),
        }),

        ("Безопасность и сессии", {
            "classes": ("wide", "collapse"),
            "fields": (
                ("admin_session_timeout_min", "ref_attribution_window_days"),
            ),
        }),

        ("Требует перезагрузки сервера", {
            "classes": ("wide", "collapse"),
            "fields": (("admin_path", "otp_issuer"),),
        }),

        ("Служебное", {
            "classes": ("wide",),
            "fields": ("updated_at",),
        }),
    )

    # singleton: запрет на добавление/удаление и редирект сразу к объекту
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = SiteSetup.get_solo()
        url = reverse("admin:app_main_sitesetup_change", args=[obj.pk])
        return admin.redirects.redirect(url)

    def render_change_form(self, request, context, *args, **kwargs):
        # Кликабельные ссылки на robots под текущим хостом
        scheme = "https" if not settings.DEBUG else "http"
        domain = request.get_host()
        robots_url = f"{scheme}://{domain}{reverse('robots_txt')}"

        form = context.get("adminform").form
        if "robots_txt" in form.fields:
            base_help = form.fields["robots_txt"].help_text or ""
            form.fields["robots_txt"].help_text = mark_safe(
                f'{base_help}<br>'
                f'<a href="{robots_url}" target="_blank">↗ robots.txt</a>'
            )

        return super().render_change_form(request, context, *args, **kwargs)

    # --- АУДИТ: отправка алерта в Telegram при изменении SiteSetup ---------------
    def save_model(self, request, obj: SiteSetup, form, change):
        # Получим оригинал из БД (до сохранения) для diff
        original = None
        if change and obj.pk:
            try:
                original = SiteSetup.objects.get(pk=obj.pk)
            except SiteSetup.DoesNotExist:
                original = None

        # Сохраняем как обычно
        super().save_model(request, obj, form, change)

        # Если не было оригинала — это не наш кейс (singleton существует), выходим
        if not original:
            return

        # Собираем diff только по реально изменённым полям
        # label_map: verbose_name для человекочитаемых названий
        label_map = {f.name: (getattr(f, "verbose_name", f.name) or f.name) for f in obj._meta.fields}
        changes = diff_sitesetup(original, obj, label_map)
        if not changes:
            return

        # Параметры отправки из актуальных настроек
        setup = SiteSetup.get_solo()
        token = (setup.telegram_bot_token or "").strip()
        chat_id = (setup.telegram_chat_id or "").strip()
        if not token or not chat_id:
            return  # канал не настроен — тихо выходим

        # Метаданные
        user_email = getattr(request.user, "email", "") or getattr(request.user, "username", "")
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
        ua = request.META.get("HTTP_USER_AGENT", "")

        # Формируем сообщение и шлём
        _, message = format_telegram_message(user_email, ip, ua, changes, label_map)
        send_telegram_message(token, chat_id, message)


# Регистрация
admin.site.register(SiteSetup, SiteSetupAdmin)
