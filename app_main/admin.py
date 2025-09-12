import django.contrib.sites.admin  # НЕ УДАЛЯТЬ
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django import forms
from django.conf import settings
from django.urls import reverse
from django.contrib.sites.models import Site
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.shortcuts import redirect
from .models import SiteSetup

User = get_user_model()


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


@admin.register(SiteSetup)
class SiteSetupAdmin(admin.ModelAdmin):
    list_display = ("domain", "domain_view", "admin_path", "otp_issuer", "block_indexing")

    fieldsets = (
        (_("Общие"), {
            "fields": ("domain", "domain_view"),
            "description": None,
        }),
        (_("Требует перезагрузки сервера"), {
            "fields": ("admin_path", "otp_issuer"),
            "description": mark_safe(
                _("Изменения этих полей вступят в силу для всех процессов только после "
                  "<strong>перезапуска приложения/процесса</strong>.")
            ),
        }),
        (_("SEO / robots.txt"), {
            "fields": ("block_indexing", "robots_txt"),
            "description": "",  # наполним динамически в render_change_form
        }),
    )

    # запрещаем добавление/удаление — это синглтон
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # вместо списка — сразу форма единственной записи
    def changelist_view(self, request, extra_context=None):
        obj = SiteSetup.get_solo()
        url = reverse("admin:app_main_sitesetup_change", args=[obj.pk])
        return redirect(url)

    def render_change_form(self, request, context, *args, **kwargs):
        # Подготовим кликабельные ссылки на robots/sitemap под текущим доменом:
        scheme = "https" if not settings.DEBUG else "http"

        domain = request.get_host()

        robots_url = f"{scheme}://{domain}{reverse('robots_txt')}"
        sitemap_url = f"{scheme}://{domain}{reverse('sitemap')}"

        # Также дополним help_text у поля robots_txt ссылками (удобно рядом с textarea)
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
