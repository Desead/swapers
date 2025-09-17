from __future__ import annotations
from django.db.models import Q
from django import forms
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.urls import reverse
from django.shortcuts import redirect
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from .models import SiteSetup
from app_main.models_security import BlocklistEntry
from .utils.telegram import send_telegram_message
from .utils.audit import diff_sitesetup, format_telegram_message
from django.conf import settings
from django.contrib import admin, messages
from django.utils import timezone
from axes.models import AccessAttempt, AccessFailureLog
from axes.utils import reset

User = get_user_model()


class UserCreationForm(forms.ModelForm):
    """Форма создания пользователя в админке (логин по email)."""
    password1 = forms.CharField(label=_("Пароль"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("Повторите пароль"), widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "phone", "company", "language")

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(_("Пользователь с таким email уже существует."))
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", _("Пароли не совпадают"))
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = (user.email or "").lower().strip()
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    """Форма изменения пользователя в админке."""
    password = ReadOnlyPasswordHashField(
        label=_("Хеш пароля"),
        help_text=_('Пароль не хранится в явном виде. '
                    'Вы можете сменить пароль по кнопке "Изменить пароль" на странице пользователя.')
    )

    class Meta:
        model = User
        fields = (
            "email", "password",
            "first_name", "last_name", "phone", "company", "language",
            "is_active", "is_staff", "is_superuser",
            "groups", "user_permissions",
            "referred_by", "referral_code", "count", "balance",
            "referral_first_seen_at", "referral_signup_delay",
            "last_login", "date_joined",
        )

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        qs = User.objects.filter(email=email).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(_("Пользователь с таким email уже существует."))
        return email


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Админка для кастомной модели User (логин по email)."""
    add_form = UserCreationForm
    form = UserChangeForm
    model = User

    list_display = ("email", "first_name", "last_name", "is_staff", "is_active", "date_joined", "referred_by")
    list_filter = ("is_staff", "is_superuser", "is_active", "language")
    search_fields = ("email", "first_name", "last_name", "referral_code", "phone", "company")
    ordering = ("-date_joined",)  # новые пользователи сверху
    filter_horizontal = ("groups", "user_permissions")

    readonly_fields = (
        "last_login", "date_joined",
        "referral_code", "referral_first_seen_at", "referral_signup_delay",
        "count",
    )

    fieldsets = (
        (_("Аутентификация"), {"fields": ("email", "password")}),
        (_("Профиль"), {"fields": ("first_name", "last_name", "phone", "company", "language")}),
        (_("Права доступа"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("Партнёрка"), {"fields": ("referred_by", "referral_code", "count", "balance",
                                     "referral_first_seen_at", "referral_signup_delay")}),
        (_("Служебное"), {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "email", "password1", "password2",
                "first_name", "last_name", "phone", "company", "language",
                "is_active", "is_staff", "is_superuser", "groups",
            ),
        }),
    )


@admin.register(SiteSetup)
class SiteSetupAdmin(admin.ModelAdmin):
    save_on_top = True

    # По умолчанию URLField в админке будет считать https-схему
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

        (_("Интеграции: XML, <head>, Telegram"), {
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
        (_("Контакты и соцсети"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("social_tg",),
                ("social_dzen",),
                ("social_rutube",),
                ("social_vk",),
                ("social_youtube",),
                ("social_instagram",),

                ("contact_label_clients", "contact_email_clients",),
                ("contact_label_partners", "contact_email_partners",),
                ("contact_label_general", "contact_email_general",),
            ),
        }),
        (_("Twitter Cards"), {
            "classes": ("wide", "collapse"),
            "fields": (
                "twitter_cards_enabled",
                "twitter_card_type",
                ("twitter_site", "twitter_creator"),
                ("twitter_image", "twitter_image_preview"),
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
                "seo_default_description",
                "seo_default_keywords",
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
        }),

        (_("Структурированные данные (JSON-LD)"), {
            "classes": ("wide", "collapse"),
            "fields": (
                "jsonld_enabled",
                ("jsonld_organization", "jsonld_website",),
            ),
        }),

        (_("CSP и интеграции"), {
            "classes": ("wide", "collapse"),
            "fields": (
                "csp_report_only",
                ("csp_extra_script_src", "csp_extra_style_src"),
                ("csp_extra_img_src", "csp_extra_connect_src"),
                ("csp_extra_frame_src", "csp_extra_font_src"),
            ),
        }),

        (_("Почтовые настройки"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("email_host", "email_port"),
                ("email_host_user", "email_host_password"),
                ("email_from",),
                "email_use_tls", "email_use_ssl",
            ),
        }),

        (_("Безопасность и сессии"), {
            "classes": ("wide", "collapse"),
            "fields": (("admin_session_timeout_min", "ref_attribution_window_days"),),
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
        # Кликабельная ссылка на robots.txt под текущим хостом
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

    # ---- превью изображений (read-only) ----
    @admin.display(description=_("Превью OG"))
    def og_image_preview(self, obj: SiteSetup):
        try:
            if obj and obj.og_image and obj.og_image.url:
                return mark_safe(
                    f'<img src="{obj.og_image.url}" style="max-width:360px;height:auto;border:1px solid #ddd;border-radius:4px;">'
                )
        except Exception:
            pass
        return "—"

    @admin.display(description=_("Превью Twitter"))
    def twitter_image_preview(self, obj: SiteSetup):
        try:
            if obj and obj.twitter_image and obj.twitter_image.url:
                return mark_safe(
                    f'<img src="{obj.twitter_image.url}" style="max-width:360px;height:auto;border:1px solid #ddd;border-radius:4px;">'
                )
        except Exception:
            pass
        return "—"

    # ---- Telegram-алерт при изменении ----
    def save_model(self, request, obj: SiteSetup, form, change):
        original = None
        if change and obj.pk:
            try:
                original = SiteSetup.objects.get(pk=obj.pk)
            except SiteSetup.DoesNotExist:
                original = None

        super().save_model(request, obj, form, change)

        if not original:
            return

        # дифф полей
        label_map = {f.name: (getattr(f, "verbose_name", f.name) or f.name) for f in obj._meta.fields}
        changes = diff_sitesetup(original, obj, label_map)
        if not changes:
            return

        # если есть токен/чат — шлём алерт
        token = (obj.telegram_bot_token or "").strip()
        chat_id = (obj.telegram_chat_id or "").strip()
        if not token or not chat_id:
            return

        user_email = getattr(request.user, "email", "") or getattr(request.user, "username", "")
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
        ua = request.META.get("HTTP_USER_AGENT", "")

        _, message = format_telegram_message(user_email, ip, ua, changes, label_map)
        send_telegram_message(token, chat_id, message)


@admin.register(BlocklistEntry)
class BlocklistEntryAdmin(admin.ModelAdmin):
    list_display = ("user", "email", "ip_address", "is_active", "reason", "created_at")
    list_filter = ("is_active",)
    search_fields = ("email", "ip_address", "user__email", "reason")
    actions = ["activate_selected", "deactivate_selected"]

    @admin.action(description="Activate selected")
    def activate_selected(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="Deactivate selected")
    def deactivate_selected(self, request, queryset):
        queryset.update(is_active=False)


# Снимаем стандартную регистрацию, чтобы переопределить отображение
try:
    admin.site.unregister(AccessAttempt)
except admin.sites.NotRegistered:
    pass


def _get_cooloff():
    """Возвращает timedelta ‘окна охлаждения’ Axes, учитывая что оно
    может быть значением или коллэйблом."""
    cooloff = getattr(settings, "AXES_COOLOFF_TIME", None)
    if callable(cooloff):
        cooloff = cooloff()
    return cooloff


def _last_failure_dt(obj: AccessAttempt):
    """Берём время **последней** неудачи по той же паре (ip, username)
    из AccessFailureLog. Если лога нет — пробуем поля попытки."""
    qs = AccessFailureLog.objects.filter(
        ip_address=obj.ip_address or "",
        username=obj.username or "",
    ).order_by("-attempt_time")

    last = qs.values_list("attempt_time", flat=True).first()
    # запасной вариант для разных версий Axes
    return last or getattr(obj, "latest_attempt", None) or getattr(obj, "attempt_time", None)


try:
    # одни версии
    from axes.utils import reset as axes_reset
except Exception:
    # другие версии
    from axes.utils.reset import reset as axes_reset  # type: ignore

from axes.models import AccessAttempt, AccessFailureLog


def _axes_reset_compat(*, ip: str | None = None, username: str | None = None) -> None:
    """
    Сбрасывает блокировки/счётчики для указанного ip и/или username.
    Поддерживает разные сигнатуры django-axes и даёт безопасный fallback.
    """
    # 1) пробуем привычные имена аргументов
    try:
        kwargs = {}
        if ip:
            kwargs["ip_address"] = ip
        if username:
            kwargs["username"] = username
        axes_reset(**kwargs)  # type: ignore[arg-type]
        return
    except TypeError:
        pass

    # 2) пробуем альтернативные имена
    try:
        kwargs = {}
        if ip:
            kwargs["ip"] = ip
        if username:
            kwargs["username"] = username
        axes_reset(**kwargs)  # type: ignore[arg-type]
        return
    except TypeError:
        pass


@admin.register(AccessAttempt)
class AccessAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "attempt_time",
        "username",
        "ip_address",
        "failures_since_start",
        "blocked_until",
        "lock_key_type",
    )
    search_fields = ("ip_address", "username", "path_info", "user_agent")
    list_filter = ("ip_address",)
    actions = ("reset_lock_ip", "reset_lock_username", "reset_lock_both")

    @admin.display(description="Ключ блокировки")
    def lock_key_type(self, obj):
        u = (obj.username or "").strip()
        ip = (obj.ip_address or "").strip()
        if u and ip:
            return "Логин + IP"
        if ip and not u:
            return "IP"
        if u and not ip:
            return "Логин"
        return "—"

    # ----- колонки -----
    def blocked_until(self, obj):
        cooloff = _get_cooloff()
        limit = getattr(settings, "AXES_FAILURE_LIMIT", 5)
        if not cooloff:
            return "—"
        last = _last_failure_dt(obj)
        if not last or (obj.failures_since_start or 0) < limit:
            return "—"
        return timezone.localtime(last + cooloff)

    blocked_until.short_description = "Заблокирован до"

    def is_blocked_now(self, obj):
        cooloff = _get_cooloff()
        limit = getattr(settings, "AXES_FAILURE_LIMIT", 5)
        last = _last_failure_dt(obj)
        if not cooloff or not last or (obj.failures_since_start or 0) < limit:
            return False
        return timezone.now() < (last + cooloff)

    is_blocked_now.boolean = True
    is_blocked_now.short_description = "Заблокирован?"

    def path_info_short(self, obj):
        return (obj.path_info or "")[:80]

    path_info_short.short_description = "Путь"

    def user_agent_short(self, obj):
        ua = obj.user_agent or ""
        return (ua[:80] + "…") if len(ua) > 80 else ua

    user_agent_short.short_description = "User-Agent"

    # ----- экшены -----
    def get_actions(self, request):
        actions = super().get_actions(request)
        # Убираем дефолтный экшен Django
        actions.pop("delete_selected", None)
        return actions

    @admin.action(description="Снять блокировку по логину")
    def reset_lock_username(modeladmin, request, queryset):
        usernames = {obj.username for obj in queryset if obj.username}
        for u in usernames:
            _axes_reset_compat(username=u)
        modeladmin.message_user(request, f"Снята блокировка для {len(usernames)} логинов.")

    @admin.action(description="Снять блокировку по IP")
    def reset_lock_ip(modeladmin, request, queryset):
        ips = {obj.ip_address for obj in queryset if obj.ip_address}
        for ip in ips:
            _axes_reset_compat(ip=ip)
        modeladmin.message_user(request, f"Снята блокировка для {len(ips)} IP.")

    @admin.action(description="Снять блокировку (логин + IP)")
    def reset_lock_both(modeladmin, request, queryset):
        pairs = {(obj.username, obj.ip_address) for obj in queryset if obj.username or obj.ip_address}
        for username, ip in pairs:
            _axes_reset_compat(username=username or None, ip=ip or None)
        modeladmin.message_user(request, f"Снята блокировка для {len(pairs)} сочетаний логин+IP.")

    def has_delete_permission(self, request, obj=None):
        return False
