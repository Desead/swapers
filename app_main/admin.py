from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django import forms
from django.db import models
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.contrib.sites.models import Site
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html

from .models import SiteSetup
import django.contrib.sites.admin  # не удалять

User = get_user_model()


# ======= User admin (без изменений) =======

class UserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label=_("Пароль"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("Подтверждение пароля"), widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email",)

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError(_("Пароли не совпадают."))
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    password = ReadOnlyPasswordHashField(label=_("Хэш пароля"))

    class Meta:
        model = User
        fields = (
            "email", "password",
            "first_name", "last_name", "phone", "company", "language",
            "is_active", "is_staff", "is_superuser", "groups", "user_permissions",
            "referred_by", "referral_code", "count", "balance",
        )

    def clean_password(self):
        return self.initial["password"]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm

    list_display = (
        "email", "first_name", "last_name", "phone", "company",
        "is_staff", "is_active",
        "count", "balance",
        "referred_by", "referral_code",
    )
    list_filter = ("is_staff", "is_superuser", "is_active")
    search_fields = ("email", "first_name", "last_name", "phone", "company", "referral_code")
    ordering = ("email",)
    readonly_fields = ("referral_code",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Персональные данные"), {"fields": ("first_name", "last_name", "phone", "company", "language")}),
        (_("Партнёрская программа"), {"fields": ("referred_by", "referral_code", "count", "balance")}),
        (_("Права"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("Даты"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "password1", "password2", "is_active", "is_staff", "is_superuser"),
        }),
    )


# ======= SiteSetup admin =======
@admin.register(SiteSetup)
class SiteSetupAdmin(admin.ModelAdmin):
    save_on_top = True
    formfield_overrides = {
        models.URLField: {"assume_scheme": "https"},
    }
    readonly_fields = (
        "updated_at",
        "og_image_width", "og_image_height",
        "og_image_preview", "twitter_image_preview",
    )

    fieldsets = (
        (_("Главная страница"), {
            "classes": ("wide",),
            "fields": ("main_h1", "main_subtitle", ("domain", "domain_view"), "maintenance_mode",),
        }),

        (_("Брендинг"), {
            "classes": ("wide", "collapse"),
            "fields": (("logo", "favicon"),),
        }),
        (_("Комиссии и списки стейблкоинов"), {
            "classes": ("wide", "collapse"),
            "fields": (("stablecoins", "fee_percent",),),
        }),

        (_("Интеграции: XML, head, Telegram"), {
            "classes": ("wide", "collapse"),
            "fields": ("head_inject_html", "xml_export_path", ("telegram_bot_token", "telegram_chat_id"),),
        }),

        (_("График работы (UTC)"), {
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
        (_("Соцсети"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("social_tg",),
                ("social_vk",),
                ("social_youtube",),
                ("social_instagram",),
                ("social_dzen",),
                ("social_rutube",),
            ),
        }),

        (_("Контакты"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("contact_label_clients", "contact_email_clients"),
                ("contact_label_partners", "contact_email_partners"),
                ("contact_label_general", "contact_email_general"),
                ("contact_telegram"),
            ),
        }),

        (_("Twitter Cards"), {
            "classes": ("wide", "collapse"),
            "fields": (
                "twitter_cards_enabled",
                "twitter_card_type",
                ("twitter_site", "twitter_creator"),
                ("twitter_image",),
                "twitter_image_preview",
            ),
        }),

        (_("SEO"), {
            "classes": ("wide", "collapse"),
            "fields": (
                "use_https_in_meta",
                "hreflang_enabled",
                "hreflang_xdefault",
                "block_indexing",
                "robots_txt",
                "seo_default_title",
                ("seo_default_description", "seo_default_keywords"),
            ),
        }),

        (_("Open Graph"), {
            "classes": ("wide", "collapse"),
            "fields": (
                "og_enabled",
                ("og_type_default", "og_locale_default"),
                ("og_title",),
                ("og_description",),
                ("og_image", "og_image_alt"),
                ("og_image_width", "og_image_height"),
                "og_image_preview",
                ("og_locale_alternates",),
            ),
            "description": _("Рекомендуемый размер 1200×630 (соотношение ~1.91:1). Минимум — 600×315.")
        }),

        (_("Структурированные данные (JSON-LD)"), {
            "classes": ("wide", "collapse"),
            "fields": (
                "jsonld_enabled",
                ("jsonld_organization", "jsonld_website",),
            ),
        }),

        (_("Почтовые настройки"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("email_host", "email_port"),
                ("email_host_user", "email_host_password"),
                ("email_from"),
                "email_use_tls", "email_use_ssl",
            ),
        }),

        (_("Безопасность и сессии (cookies)"), {
            "classes": ("wide", "collapse"),
            "description": _(
                "Last click wins — последний клик по реферальной ссылке действует до регистрации. "
                "После успешной привязки временная cookie удаляется."
            ),
            "fields": ("admin_session_timeout_min", "ref_attribution_window_days",),
        }),

        (_("Требует перезагрузки сервера"), {
            "classes": ("wide", "collapse"),
            "fields": (("admin_path", "otp_issuer"),),
        }),

        (_("Служебное"), {
            "classes": ("wide",),
            "fields": ("updated_at",),
        }),

    )

    # плейсхолдеры для названий почтовых блоков
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if formfield and db_field.name in {
            "contact_label_clients", "contact_label_partners", "contact_label_general"
        }:
            placeholders = {
                "contact_label_clients": _("Почта для клиентов"),
                "contact_label_partners": _("Почта для партнёров"),
                "contact_label_general": _("Почта для общих вопросов"),
            }
            formfield.widget.attrs.setdefault("placeholder", placeholders[db_field.name])
        return formfield

    # превью картинок в админке
    def og_image_preview(self, obj):
        if getattr(obj, "og_image", None):
            return format_html(
                '<img src="{}" style="max-width:480px;height:auto;border:1px solid #ddd;'
                'border-radius:6px;box-shadow:0 1px 2px rgba(0,0,0,.08);" alt="">',
                obj.og_image.url
            )
        return format_html('<span style="opacity:.7;">{}</span>', _("Изображение не загружено"))

    og_image_preview.short_description = _("OG: превью")

    def twitter_image_preview(self, obj):
        if getattr(obj, "twitter_image", None):
            return format_html(
                '<img src="{}" style="max-width:480px;height:auto;border:1px solid #ddd;'
                'border-radius:6px;box-shadow:0 1px 2px rgba(0,0,0,.08);" alt="">',
                obj.twitter_image.url
            )
        return format_html('<span style="opacity:.7;">{}</span>', _("Изображение не загружено"))

    twitter_image_preview.short_description = _("Twitter: превью")

    # singleton: запрет на добавление/удаление и редирект сразу к объекту
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = SiteSetup.get_solo()
        url = reverse("admin:app_main_sitesetup_change", args=[obj.pk])
        return redirect(url)

    def render_change_form(self, request, context, *args, **kwargs):
        # Кликабельные ссылки на robots/sitemap под текущим хостом
        scheme = "https" if not settings.DEBUG else "http"
        domain = request.get_host()
        robots_url = f"{scheme}://{domain}{reverse('robots_txt')}"
        # sitemap_url = f"{scheme}://{domain}{reverse('sitemap')}"

        form = context.get("adminform").form
        if "robots_txt" in form.fields:
            base_help = form.fields["robots_txt"].help_text or ""
            form.fields["robots_txt"].help_text = mark_safe(
                f'{base_help}<br>'
                f'<a href="{robots_url}" target="_blank">↗ robots.txt</a>'
                # f'<a href="{sitemap_url}" target="_blank">↗ sitemap.xml</a>'
            )

        return super().render_change_form(request, context, *args, **kwargs)


try:
    admin.site.unregister(Site)
except admin.sites.NotRegistered:
    pass
