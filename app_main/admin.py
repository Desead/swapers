from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django import forms
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.contrib.sites.models import Site
from django.conf import settings
from django.utils.translation import gettext_lazy as _

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

    readonly_fields = ("updated_at",)

    # ПЕРВЫЙ блок раскрыт, остальные свёрнуты
    fieldsets = (
        (_("Главная страница"), {
            "classes": ("wide",),
            "fields": ("main_h1", "main_subtitle", ("domain", "domain_view"), "maintenance_mode",),

        }),
        (_("Брендинг"), {
            "classes": ("wide", "collapse"),
            "fields": (("logo", "favicon"),),
        }),

        (_("SEO / robots.txt"), {
            "classes": ("wide", "collapse"),
            "fields": (
                "block_indexing",
                "robots_txt",

                "seo_default_description",
                "seo_default_keywords",
                "seo_default_title",
            ),
            "description": "",  # дополним ссылками ниже
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
            "description": mark_safe(
                _("Время хранится в формате UTC. Значения по умолчанию соответствуют графику по Москве <strong>(пн–пт 10:00–22:00, сб–вс 12:00–20:00)</strong>. При изменении учитывайте разницу с МСК (UTC+3).")
            ),
        }),

        (_("Комиссии и списки"), {
            "classes": ("wide", "collapse"),
            "fields": (("stablecoins", "fee_percent",),),
        }),

        (_("Интеграции: XML и вставка в <head>"), {
            "classes": ("wide", "collapse"),
            "fields": (("head_inject_html", "xml_export_path",),),
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

        (_("Интеграции: Telegram"), {
            "classes": ("wide", "collapse"),
            "fields": (("telegram_bot_token", "telegram_chat_id"),),
        }),

        (_("Контакты и соцсети"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("social_tg", "contact_email_clients",),
                ("social_vk", "contact_email_partners",),
                ("social_youtube", "contact_email_general",),
                ("social_instagram", "contact_telegram",),
                ("social_dzen",),
                ("social_rutube",),
                ("social_twitter",),
            ),
        }),

        (_("Требует перезагрузки сервера"), {
            "classes": ("wide", "collapse"),
            "fields": (("admin_path", "otp_issuer"),),
            "description": mark_safe(
                _("Изменения этих полей вступят в силу для всех процессов только после "
                  "<strong>перезапуска приложения/процесса</strong>.")
            ),
        }),
        (_("Служебное"), {
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
        return redirect(url)

    def render_change_form(self, request, context, *args, **kwargs):
        # Кликабельные ссылки на robots/sitemap под текущим хостом
        scheme = "https" if not settings.DEBUG else "http"
        domain = request.get_host()
        robots_url = f"{scheme}://{domain}{reverse('robots_txt')}"
        sitemap_url = f"{scheme}://{domain}{reverse('sitemap')}"

        form = context.get("adminform").form
        if "robots_txt" in form.fields:
            base_help = form.fields["robots_txt"].help_text or ""
            form.fields["robots_txt"].help_text = mark_safe(
                f'{base_help}<br>'
                f'<a href="{robots_url}" target="_blank">↗ robots.txt</a> &nbsp;|&nbsp; '
                f'<a href="{sitemap_url}" target="_blank">↗ sitemap.xml</a>'
            )

        return super().render_change_form(request, context, *args, **kwargs)


# Скрываем стандартную модель "Сайты" из админки
try:
    admin.site.unregister(Site)
except admin.sites.NotRegistered:
    pass
