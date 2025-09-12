from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django import forms
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.contrib.sites.models import Site
from django.utils.translation import gettext_lazy as _
import django.contrib.sites.admin  # НЕ УДАЛЯТЬ — чтобы модель "Site" зарегистрировалась, затем мы её скрываем.

from .models import SiteSetup

User = get_user_model()


# -------- Пользователи --------

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
            from django.core.exceptions import ValidationError
            raise ValidationError(_("Пароли не совпадают."))
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


# -------- Настройки сайта / robots.txt --------

class SiteSetupAdminForm(forms.ModelForm):
    class Meta:
        model = SiteSetup
        fields = "__all__"
        widgets = {
            "robots_txt": forms.Textarea(attrs={
                "rows": 16,
                "style": "font-family:monospace; white-space:pre; font-size:13px;",
            }),
        }


@admin.register(SiteSetup)
class SiteSetupAdmin(admin.ModelAdmin):
    form = SiteSetupAdminForm
    save_on_top = True

    list_display = ("domain", "domain_view", "admin_path", "otp_issuer")
    readonly_fields = ("robots_txt_link",)

    fieldsets = (
        (_("Общие"), {
            "fields": ("domain", "domain_view"),
        }),
        (_("Требует перезагрузки сервера"), {
            "fields": ("admin_path", "otp_issuer"),
            "description": mark_safe(
                _("Изменения этих полей вступят в силу для всех процессов только после "
                  "<strong>перезапуска приложения/процесса</strong>.")
            ),
        }),
        (_("SEO / robots.txt"), {
            "fields": ("robots_txt_link", "robots_txt"),
            "description": mark_safe(_(
                "Задайте полный текст ответа <code>/robots.txt</code>. "
                "Строка вида <code>Sitemap: https://&lt;host&gt;/sitemap.xml</code> "
                "добавляется автоматически во view."
            )),
        }),
    )

    def robots_txt_link(self, obj):
        return mark_safe('<a href="/robots.txt" target="_blank" rel="noopener">/robots.txt ↗</a>')
    robots_txt_link.short_description = _("Текущий robots.txt")

    # это синглтон — добавлять/удалять нельзя
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # вместо списка — сразу форма единственной записи
    def changelist_view(self, request, extra_context=None):
        obj = SiteSetup.get_solo()
        url = reverse("admin:app_main_sitesetup_change", args=[obj.pk])
        return redirect(url)


# Скрываем стандартную модель "Сайты" из админки
try:
    admin.site.unregister(Site)
except admin.sites.NotRegistered:
    pass
