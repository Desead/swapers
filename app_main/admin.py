from __future__ import annotations
from django.contrib.sites import admin  # НЕ УДАЛЯТЬ. ЗАГРУЖАЕМ САЙТ ЧТОБЫ СМОГЛИ СНЯТЬ ЕГО РЕГИСТРАЦИЮ В АДМИНКЕ!
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.db.models import Sum
from axes.utils import reset as axes_reset
from .models import SiteSetup
from app_main.models_security import BlocklistEntry
from .utils.telegram import send_telegram_message
from .utils.audit import diff_sitesetup, format_telegram_message
from axes.models import AccessAttempt, AccessFailureLog
from django.conf import settings
from django.utils.translation import get_language, gettext_lazy as _t
from django.utils.safestring import mark_safe
from django.urls import reverse
from django.shortcuts import redirect
from parler.admin import TranslatableAdmin
from parler.forms import TranslatableModelForm
from django.core.exceptions import FieldDoesNotExist
from django.contrib.admin.sites import NotRegistered
from django.contrib.sites.models import Site
from app_main.models_monitoring import Monitoring
from django.utils import timezone
from decimal import Decimal
from django import forms
from django.contrib import admin as djadmin
from django.db import models
from django.contrib.admin.widgets import RelatedFieldWidgetWrapper
from .models_documents import Document
from django.utils.text import slugify
from app_library.models import DocumentTemplate


# --- UNIFIED PARLER LANGUAGE CHIPS MIXIN -------------------------------------
class ParlerLanguageChipsMixin:
    """Единый UI для переключения языков (Parler) без правок шаблонов."""

    def _lang_codes(self):
        return [code.lower() for code, _ in getattr(settings, "LANGUAGES", (("ru", "Russian"),))]

    def get_form_language(self, request, obj=None):
        # 1) Язык из query (?language=xx) — всегда самый высокий приоритет
        lang = request.GET.get("language")
        if lang:
            if hasattr(request, "session"):
                request.session["PARLER_CURRENT_LANGUAGE"] = lang
            return lang

        # 2) Если мы СОЗДАЁМ документ (obj is None) — всегда дефолт проекта
        if obj is None:
            return getattr(settings, "LANGUAGE_CODE", "ru")

        # 3) Иначе: из сессии (чипы), далее — текущая активная локаль, далее — дефолт
        if hasattr(request, "session"):
            return request.session.get("PARLER_CURRENT_LANGUAGE") or (get_language() or settings.LANGUAGE_CODE)
        return get_language() or settings.LANGUAGE_CODE

    @djadmin.display(description=_t("Языки"))
    def language_toolbar(self, obj=None):
        cur = (get_language() or settings.LANGUAGE_CODE or "ru").lower()
        chips = []
        base_css = (
            "display:inline-block;margin:0 6px 6px 0;padding:2px 10px;"
            "border-radius:999px;font-size:12px;text-decoration:none;"
        )
        for code in self._lang_codes():
            try:
                has = obj.has_translation(code) if obj else False
            except Exception:
                has = False
            bg = "#2e7d32" if has else "#9e9e9e"  # зелёный / серый
            ring = "box-shadow:0 0 0 2px #00000022 inset;" if code == cur else ""
            chips.append(
                f'<a href="?language={code}" '
                f'style="{base_css}background:{bg};color:#fff;{ring}">{code.upper()}</a>'
            )
        return mark_safe("".join(chips))

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if "language_toolbar" not in ro:
            ro.append("language_toolbar")
        return ro

    def get_fieldsets(self, request, obj=None):
        fs = list(super().get_fieldsets(request, obj))
        if not any("language_toolbar" in (f[1].get("fields") or ()) for f in fs):
            fs.insert(0, (_t("Языки"), {"fields": ("language_toolbar",), "classes": ("wide",)}))
        return fs

    def _append_language_query(self, request, response):
        """
        Всегда дописываем ?language=<текущий> к редиректу после save,
        чтобы форма/чипы и Parler были в одном языке.
        """
        try:
            is_redirect = getattr(response, "status_code", 200) in (301, 302, 303, 307, 308)
            has_location = "Location" in response
        except Exception:
            return response
        if not (is_redirect and has_location):
            return response

        # берём язык так же, как и форма его берёт
        lang = self.get_form_language(request) or (get_language() or settings.LANGUAGE_CODE)
        if not lang:
            return response

        from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
        parts = urlparse(response["Location"])
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        if query.get("language") != lang:
            query["language"] = lang
            response["Location"] = urlunparse(parts._replace(query=urlencode(query)))
        return response

    def response_change(self, request, obj):
        return self._append_language_query(request, super().response_change(request, obj))

    def response_post_save_add(self, request, obj):
        return self._append_language_query(request, super().response_post_save_add(request, obj))

    def response_post_save_change(self, request, obj):
        return self._append_language_query(request, super().response_post_save_change(request, obj))


# --- /UNIFIED MIXIN ----------------------------------------------------------


class DecimalPlainWidget(forms.NumberInput):
    """Показывает Decimal как фиксированное число (без экспоненты)."""

    def __init__(self, *, decimal_places=None, **kwargs):
        self.decimal_places = 5 if decimal_places is None else decimal_places
        super().__init__(**kwargs)

    def format_value(self, value):
        if isinstance(value, Decimal):
            q = Decimal(1).scaleb(-self.decimal_places)  # 1E-places
            return format(value.quantize(q), "f")
        return super().format_value(value)


class DecimalFormatMixin:
    """Подставляет DecimalPlainWidget для всех DecimalField в форме админки."""

    def formfield_for_dbfield(self, db_field, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, **kwargs)
        if isinstance(db_field, models.DecimalField) and formfield:
            formfield.widget = DecimalPlainWidget(decimal_places=db_field.decimal_places)
        return formfield


User = get_user_model()


# ======================= Пользователи =======================

class UserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label=_t("Пароль"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_t("Повторите пароль"), widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "phone", "company", "language")

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(_t("Пользователь с таким email уже существует."))
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", _t("Пароли не совпадают"))
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = (user.email or "").lower().strip()
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    password = ReadOnlyPasswordHashField(
        label=_t("Хеш пароля"),
        help_text=_t('Пароль не хранится в явном виде. '
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
            raise forms.ValidationError(_t("Пользователь с таким email уже существует."))
        return email


@djadmin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    model = User
    save_on_top = True

    list_display = ("email", "first_name", "last_name", "is_staff", "is_active", "date_joined", "referred_by")
    list_filter = ("is_staff", "is_superuser", "is_active", "language")
    search_fields = ("email", "first_name", "last_name", "referral_code", "phone", "company")
    ordering = ("-date_joined",)
    filter_horizontal = ("groups", "user_permissions")

    readonly_fields = (
        "last_login", "date_joined",
        "referral_code", "referral_first_seen_at", "referral_signup_delay",
        "count",
    )

    fieldsets = (
        (_t("Аутентификация"), {"fields": ("email", "password")}),
        (_t("Профиль"), {"fields": ("first_name", "last_name", "phone", "company", "language")}),
        (_t("Права доступа"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_t("Партнёрка"), {"fields": ("referred_by", "referral_code", "count", "balance",
                                      "referral_first_seen_at", "referral_signup_delay")}),
        (_t("Служебное"), {"fields": ("last_login", "date_joined")}),
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


# ======================= Настройки сайта (SiteSetup) =======================

class SiteSetupAdminForm(TranslatableModelForm):
    site_enabled_languages = forms.MultipleChoiceField(
        choices=(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=_t("Языки, показываемые на сайте"),
        help_text=_t("Выберите языки, которые должны быть видимы на сайте (переключатель, hreflang)."),
    )

    class Meta:
        model = SiteSetup
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["site_enabled_languages"].choices = list(
            getattr(settings, "LANGUAGES", (("ru", "Russian"),))
        )
        inst = kwargs.get("instance")
        if inst is not None:
            initial = inst.site_enabled_languages or inst.get_enabled_languages()
        else:
            default = (getattr(settings, "LANGUAGE_CODE", "ru") or "ru").split("-")[0].lower()
            initial = [default]
        self.fields["site_enabled_languages"].initial = initial

    def clean_site_enabled_languages(self):
        langs = self.cleaned_data.get("site_enabled_languages") or []
        known = [code for code, _ in getattr(settings, "LANGUAGES", ())]
        known_set = {c.lower() for c in known}
        out, seen = [], set()
        for c in langs:
            cc = (c or "").lower()
            if cc in known_set and cc not in seen:
                out.append(cc)
                seen.add(cc)
        return out


@djadmin.register(SiteSetup)
class SiteSetupAdmin(ParlerLanguageChipsMixin, DecimalFormatMixin, TranslatableAdmin, djadmin.ModelAdmin):
    change_form_template = "admin/parler/change_form.html"
    save_on_top = True
    form = SiteSetupAdminForm

    formfield_overrides = {
        models.URLField: {"assume_scheme": "https"},
    }

    SITE_LANG_CHOICES = tuple(getattr(settings, "LANGUAGES", (("ru", "Russian"),)))

    readonly_fields = (
        "updated_at",
        "og_image_width", "og_image_height",
        "og_image_preview", "twitter_image_preview",
        "translation_matrix",
        "language_toolbar",
    )

    fieldsets = (
        (_t("Главная страница"), {
            "classes": ("wide",),
            "fields": ("main_h1", "main_subtitle", ("domain", "domain_view"), "maintenance_mode", "copyright_field"),
        }),
        (_t("Перевод на различные языки"), {
            "classes": ("wide", "collapse"),
            "fields": ("language_toolbar", "site_enabled_languages", "translation_matrix"),
        }),
        (_t("Брендинг"), {
            "classes": ("wide", "collapse"),
            "fields": (("logo", "favicon"),),
        }),
        (_t("Комиссии и списки стейблкоинов"), {
            "classes": ("wide", "collapse"),
            "fields": (("stablecoins", "fee_percent",),),
        }),
        (_t("Интеграции: XML, <head>, Telegram"), {
            "classes": ("wide", "collapse"),
            "fields": ("head_inject_html", "xml_export_path", ("telegram_bot_token", "telegram_chat_id")),
        }),
        (_t("График работы (UTC)"), {
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
        (_t("Контакты и соцсети"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("social_tg",),
                ("social_dzen",),
                ("social_rutube",),
                ("social_vk",),
                ("social_youtube",),
                ("social_instagram",),
                ("contact_label_clients", "contact_email_clients"),
                ("contact_label_partners", "contact_email_partners"),
                ("contact_label_general", "contact_email_general"),
            ),
        }),
        (_t("Twitter Cards"), {
            "classes": ("wide", "collapse"),
            "fields": (
                "twitter_cards_enabled",
                "twitter_card_type",
                ("twitter_site", "twitter_creator"),
                ("twitter_image", "twitter_image_preview"),
            ),
        }),
        (_t("SEO"), {
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
        (_t("Open Graph"), {
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
        (_t("Структурированные данные (JSON-LD)"), {
            "classes": ("wide", "collapse"),
            "fields": (
                "jsonld_enabled",
                ("jsonld_organization", "jsonld_website"),
            ),
        }),
        (_t("CSP и интеграции"), {
            "classes": ("wide", "collapse"),
            "fields": (
                "csp_report_only",
                ("csp_extra_script_src", "csp_extra_style_src"),
                ("csp_extra_img_src", "csp_extra_connect_src"),
                ("csp_extra_frame_src", "csp_extra_font_src"),
            ),
        }),
        (_t("Почтовые настройки"), {
            "classes": ("wide", "collapse"),
            "fields": (
                ("email_host", "email_port"),
                ("email_host_user", "email_host_password"),
                ("email_from",),
                "email_use_tls", "email_use_ssl",
            ),
        }),
        (_t("Безопасность и сессии"), {
            "classes": ("wide", "collapse"),
            "fields": (("admin_session_timeout_min", "ref_attribution_window_days"),),
        }),
        (_t("Требует перезагрузки сервера"), {
            "classes": ("wide", "collapse"),
            "fields": (("admin_path", "otp_issuer"),),
        }),
        (_t("Служебное"), {
            "classes": ("wide",),
            "fields": ("updated_at",),
        }),
    )

    def _translated_field_names(self, obj):
        try:
            return list(getattr(obj._parler_meta, "_fields_to_model", {}).keys())
        except Exception:
            return []

    def _human_field_label(self, obj, fname: str) -> str:
        try:
            f = obj._meta.get_field(fname)
            return getattr(f, "verbose_name", fname) or fname
        except FieldDoesNotExist:
            pass
        except Exception:
            pass
        try:
            tr_model = obj._parler_meta.get_model_by_field(fname)
            f = tr_model._meta.get_field(fname)
            return getattr(f, "verbose_name", fname) or fname
        except Exception:
            return fname

    @djadmin.display(description=_t("Матрица переводов"))
    def translation_matrix(self, obj):
        if not obj:
            return "—"
        fields = self._translated_field_names(obj)
        if not fields:
            return _t("Нет переводимых полей.")
        langs = [code for code, _ in getattr(settings, "LANGUAGES", (("ru", "Russian"),))]
        ths = "".join(f'<th style="padding:6px 10px;text-align:center;white-space:nowrap;">{code.upper()}</th>' for code in langs)
        rows = []
        for fname in fields:
            verbose = self._human_field_label(obj, fname)
            tds = []
            for code in langs:
                val = obj.safe_translation_getter(fname, default=None, language_code=code, any_language=False)
                ok = bool(val)
                sym = "✓" if ok else "•"
                bg = "#e8f5e9" if ok else "#ffebee"
                color = "#2e7d32" if ok else "#b71c1c"
                tds.append(f'<td style="padding:6px 10px;text-align:center;background:{bg};color:{color};">{sym}</td>')
            rows.append(f'<tr><td style="padding:6px 10px;white-space:nowrap;">{verbose}</td>{"".join(tds)}</tr>')
        table = (
            '<div style="overflow:auto;border:1px solid #eee;border-radius:8px;">'
            '<table style="width:100%;border-collapse:collapse;font-size:12px;">'
            f'<thead><tr><th style="padding:6px 10px;text-align:left;">{_t("Поле")}</th>{ths}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody>'
            '</table>'
            '<div style="padding:6px 0 0 2px;font-size:11px;color:#666;">'
            f'✓ — {_t("есть значение")}, • — {_t("пусто/нет перевода")}'
            '</div>'
            '</div>'
        )
        return mark_safe(table)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = SiteSetup.get_solo()
        url = reverse("admin:app_main_sitesetup_change", args=[obj.pk])
        return redirect(url)

    def render_change_form(self, request, context, *args, **kwargs):
        self.request = request
        scheme = "https" if not settings.DEBUG else "http"
        domain = request.get_host()
        robots_url = f"{scheme}://{domain}{reverse('robots_txt')}"
        form = context.get("adminform").form
        if "robots_txt" in form.fields:
            base_help = form.fields["robots_txt"].help_text or ""
            form.fields["robots_txt"].help_text = mark_safe(f'{base_help}<br><a href="{robots_url}" target="_blank">↗ robots.txt</a>')
        return super().render_change_form(request, context, *args, **kwargs)

    @djadmin.display(description=_t("Превью OG"))
    def og_image_preview(self, obj: SiteSetup):
        try:
            if obj and obj.og_image and obj.og_image.url:
                return mark_safe(f'<img src="{obj.og_image.url}" style="max-width:360px;height:auto;border:1px solid #ddd;border-radius:4px;">')
        except Exception:
            pass
        return "—"

    @djadmin.display(description=_t("Превью Twitter"))
    def twitter_image_preview(self, obj: SiteSetup):
        try:
            if obj and obj.twitter_image and obj.twitter_image.url:
                return mark_safe(f'<img src="{obj.twitter_image.url}" style="max-width:360px;height:auto;border:1px solid #ddd;border-radius:4px;">')
        except Exception:
            pass
        return "—"

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "site_enabled_languages" in form.base_fields:
            choices = list(getattr(settings, "LANGUAGES", ()))
            initial = []
            if obj and isinstance(getattr(obj, "site_enabled_languages", None), list):
                valid = {c for c, _ in choices}
                initial = [c for c in obj.site_enabled_languages if c in valid]
            form.base_fields["site_enabled_languages"] = forms.MultipleChoiceField(
                required=False,
                choices=choices,
                widget=forms.CheckboxSelectMultiple,
                initial=initial,
                label=form.base_fields.get("site_enabled_languages").label or _t("Языки, показывать на сайте"),
                help_text=_t("Отмеченные языки появятся в переключателе языков на сайте."),
            )
        try:
            lang = self.get_form_language(request)
            if obj is not None and hasattr(obj, "set_current_language"):
                obj.set_current_language(lang)
        except Exception:
            pass
        return form

    def save_model(self, request, obj: SiteSetup, form, change):
        if form is not None and hasattr(form, "cleaned_data"):
            allowed = [c.lower() for c, _ in getattr(settings, "LANGUAGES", ())]

            def _normalize(code: str | None) -> str | None:
                if not code:
                    return None
                c = str(code).lower().replace("_", "-")
                if c in allowed:
                    return c
                base = c.split("-", 1)[0]
                for a in allowed:
                    if a == base or a.split("-", 1)[0] == base:
                        return a
                return None

            selected = (
                    form.cleaned_data.get("site_enabled_languages")
                    or form.cleaned_data.get("site_enabled_languages_list")
                    or obj.site_enabled_languages
                    or []
            )
            norm, seen = [], set()
            for code in selected:
                n = _normalize(code)
                if n and n not in seen:
                    norm.append(n);
                    seen.add(n)
            if not norm:
                default_norm = _normalize(getattr(settings, "LANGUAGE_CODE", "")) or (allowed[0] if allowed else None)
                if default_norm:
                    norm = [default_norm]
            obj.site_enabled_languages = norm

        original = None
        if change and obj.pk:
            try:
                original = SiteSetup.objects.get(pk=obj.pk)
            except SiteSetup.DoesNotExist:
                original = None

        super().save_model(request, obj, form, change)

        if not original:
            return
        label_map = {f.name: (getattr(f, "verbose_name", f.name) or f.name) for f in obj._meta.fields}
        changes = diff_sitesetup(original, obj, label_map)
        if not changes:
            return
        token = (obj.telegram_bot_token or "").strip()
        chat_id = (obj.telegram_chat_id or "").strip()
        if not token or not chat_id:
            return
        user_email = getattr(request.user, "email", "") or getattr(request.user, "username", "")
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
        ua = request.META.get("HTTP_USER_AGENT", "")
        _, message = format_telegram_message(user_email, ip, ua, changes, label_map)
        send_telegram_message(token, chat_id, message)

    class Media:
        js = ("admin/js/jquery.init.js", "parler/js/admin/parler.js")
        css = {"all": ("parler/css/admin/parler.css",)}


# ======================= Чёрный список =======================

@djadmin.register(BlocklistEntry)
class BlocklistEntryAdmin(djadmin.ModelAdmin):
    list_display = ("user_name_view", "email", "ip_address", "is_active", "reason", "created_at")
    list_filter = ("is_active",)
    search_fields = ("email", "ip_address", "user__email", "reason")
    actions = ["activate_selected", "deactivate_selected"]

    @djadmin.action(description=_t("Активировать выбранные"))
    def activate_selected(self, request, queryset):
        queryset.update(is_active=True)

    @djadmin.action(description=_t("Деактивировать выбранные"))
    def deactivate_selected(self, request, queryset):
        queryset.update(is_active=False)

    @djadmin.display(description=_t("Пользователь"))
    def user_name_view(self, obj):
        return getattr(getattr(obj, "user", None), "email", "—")


# ======================= Axes: Попытки доступа =======================

try:
    djadmin.site.unregister(AccessAttempt)
except djadmin.sites.NotRegistered:
    pass


def _get_cooloff():
    cooloff = getattr(settings, "AXES_COOLOFF_TIME", None)
    if callable(cooloff):
        cooloff = cooloff()
    return cooloff


def _axes_param_sets():
    params = getattr(settings, "AXES_LOCKOUT_PARAMETERS", [["username", "ip_address"]])
    seq = params if isinstance(params, (list, tuple, set)) else [params]
    out = []
    for p in seq:
        if isinstance(p, str):
            out.append({p})
        else:
            out.append(set(p))
    return out


def _axes_reset_safe(*, username=None, ip=None, ip_address=None, user_agent=None):
    import inspect
    ip_norm = ip if ip is not None else ip_address
    try:
        params = inspect.signature(axes_reset).parameters
    except Exception:
        params = {}
    kwargs = {}
    if "username" in params and username is not None:
        kwargs["username"] = username
    if ip_norm is not None:
        if "ip" in params:
            kwargs["ip"] = ip_norm
        elif "ip_address" in params:
            kwargs["ip_address"] = ip_norm
    if "user_agent" in params and user_agent is not None:
        kwargs["user_agent"] = user_agent
    try:
        return axes_reset(**kwargs)
    except TypeError:
        if ip_norm is not None:
            alt = dict(kwargs)
            if "ip" in alt:
                val = alt.pop("ip")
                if "ip_address" in params:
                    alt["ip_address"] = val
            elif "ip_address" in alt:
                val = alt.pop("ip_address")
                if "ip" in params:
                    alt["ip"] = val
            try:
                return axes_reset(**alt)
            except TypeError:
                pass
        if "username" in kwargs:
            try:
                return axes_reset(username=kwargs["username"])
            except TypeError:
                pass
        raise


def _last_failure_dt_for(obj: AccessAttempt, kind: str):
    ip = (obj.ip_address or "").strip()
    user = (obj.username or "").strip()
    qs = AccessFailureLog.objects.all()
    if kind == "Логин + IP":
        if not ip or not user:
            return None
        qs = qs.filter(ip_address=ip, username=user)
        fallback_qs = AccessAttempt.objects.filter(ip_address=ip, username=user)
    elif kind == "IP":
        if not ip:
            return None
        qs = qs.filter(ip_address=ip)
        fallback_qs = AccessAttempt.objects.filter(ip_address=ip)
    elif kind == "Логин":
        if not user:
            return None
        qs = qs.filter(username=user)
        fallback_qs = AccessAttempt.objects.filter(username=user)
    else:
        return None
    last = qs.order_by("-attempt_time").values_list("attempt_time", flat=True).first()
    if last:
        return last
    return fallback_qs.order_by("-attempt_time").values_list("attempt_time", flat=True).first()


@djadmin.register(AccessAttempt)
class AccessAttemptAdmin(djadmin.ModelAdmin):
    list_display = (
        "ip_address", "username", "failures_since_start",
        "lock_key_type", "is_blocked_now", "path_info_short", "user_agent_short",
    )
    search_fields = ("ip_address", "username", "path_info", "user_agent")
    list_filter = ("ip_address",)
    actions = ("reset_lock_ip", "reset_lock_username", "reset_lock_both")

    @djadmin.display(description=_t("Тип блокировки"))
    def lock_key_type(self, obj: AccessAttempt):
        limit = int(getattr(settings, "AXES_FAILURE_LIMIT", 5) or 5)
        param_sets = _axes_param_sets()
        if {"username", "ip_address"} in param_sets and obj.username and obj.ip_address:
            pair_total = (
                    AccessAttempt.objects.filter(username=obj.username, ip_address=obj.ip_address)
                    .aggregate(s=Sum("failures_since_start"))["s"] or 0
            )
            if pair_total >= limit:
                return _t("Логин + IP")
        if {"ip_address"} in param_sets and obj.ip_address:
            ip_total = (
                    AccessAttempt.objects.filter(ip_address=obj.ip_address)
                    .aggregate(s=Sum("failures_since_start"))["s"] or 0
            )
            if ip_total >= limit:
                return _t("IP")
        if {"username"} in param_sets and obj.username:
            user_total = (
                    AccessAttempt.objects.filter(username=obj.username)
                    .aggregate(s=Sum("failures_since_start"))["s"] or 0
            )
            if user_total >= limit:
                return _t("Логин")
        for s in param_sets:
            parts = []
            if "username" in s: parts.append(_t("Логин"))
            if "ip_address" in s: parts.append(_t("IP"))
            if "user_agent" in s: parts.append(_t("User-Agent"))
            if parts:
                return " + ".join(parts)
        return "—"

    @djadmin.display(boolean=True, description=_t("Заблокирован?"))
    def is_blocked_now(self, obj):
        cooloff = _get_cooloff()
        if not cooloff:
            return False
        limit = int(getattr(settings, "AXES_FAILURE_LIMIT", 5) or 5)
        now = timezone.now()
        k = self.lock_key_type(obj)
        if k == _t("Логин + IP"):
            pair_total = (
                    AccessAttempt.objects.filter(username=obj.username, ip_address=obj.ip_address)
                    .aggregate(s=Sum("failures_since_start"))["s"] or 0
            )
            if pair_total >= limit:
                last = _last_failure_dt_for(obj, "Логин + IP")
                return bool(last and now < last + cooloff)
            return False
        if k == _t("IP"):
            ip_total = (
                    AccessAttempt.objects.filter(ip_address=obj.ip_address)
                    .aggregate(s=Sum("failures_since_start"))["s"] or 0
            )
            if ip_total >= limit:
                last = _last_failure_dt_for(obj, "IP")
                return bool(last and now < last + cooloff)
            return False
        if k == _t("Логин"):
            user_total = (
                    AccessAttempt.objects.filter(username=obj.username)
                    .aggregate(s=Sum("failures_since_start"))["s"] or 0
            )
            if user_total >= limit:
                last = _last_failure_dt_for(obj, "Логин")
                return bool(last and now < last + cooloff)
            return False
        return False

    @djadmin.display(description=_t("Путь"))
    def path_info_short(self, obj):
        return (obj.path_info or "")[:80]

    @djadmin.display(description=_t("User-Agent"))
    def user_agent_short(self, obj):
        ua = obj.user_agent or ""
        return (ua[:80] + "…") if len(ua) > 80 else ua

    def _action_guard_and_reset(self, request, queryset, expected_type: str, do_reset):
        done = skipped = 0
        for o in queryset:
            is_blocked = self.is_blocked_now(o)
            lock_type = self.lock_key_type(o)
            if not is_blocked or lock_type != expected_type:
                skipped += 1
                continue
            try:
                do_reset(o)
                done += 1
            except Exception:
                skipped += 1
        msg = _t("Снято блокировок: %(done)s. Пропущено: %(skipped)s.") % {"done": done, "skipped": skipped}
        self.message_user(request, msg)

    @djadmin.action(description=_t("Снять блокировку по IP"))
    def reset_lock_ip(self, request, queryset):
        def _do(o):
            if o.ip_address:
                _axes_reset_safe(ip=o.ip_address)

        self._action_guard_and_reset(request, queryset, expected_type=_t("IP"), do_reset=_do)

    @djadmin.action(description=_t("Снять блокировку по логину"))
    def reset_lock_username(self, request, queryset):
        def _do(o):
            if o.username:
                _axes_reset_safe(username=o.username)

        self._action_guard_and_reset(request, queryset, expected_type=_t("Логин"), do_reset=_do)

    @djadmin.action(description=_t("Снять блокировку по логину+IP"))
    def reset_lock_both(self, request, queryset):
        def _do(o):
            if o.ip_address or o.username:
                _axes_reset_safe(ip=o.ip_address, username=o.username)

        self._action_guard_and_reset(request, queryset, expected_type=_t("Логин + IP"), do_reset=_do)


# ======================= Мониторинги =======================

@djadmin.register(Monitoring)
class MonitoringAdmin(DecimalFormatMixin, djadmin.ModelAdmin):
    save_on_top = True
    list_display = ("name", "number", "is_active", "partner_type",
                    "percent", "balance_usdt", "total_profit_usdt",
                    "last_payout_at", "api_access", "clicks_total", "last_click_at",)
    autocomplete_fields = ()
    readonly_fields = ("banner_dark_preview", "banner_light_preview", "balance_usdt", "total_profit_usdt",
                       "last_payout_at", "last_payout_amount_usdt", "clicks_total", "last_click_at",)
    list_filter = ("is_active", "partner_type", "api_access")
    search_fields = ("name", "link")
    list_editable = ("is_active", "number",)
    ordering = ("last_payout_at",)

    fieldsets = (
        (_t("Основное"), {
            "classes": ("wide",),
            "fields": ("name", "link", "number", "is_active",),
        }),
        (_t("Условия партнёрки"), {
            "description": _t(
                "100% партнёру от прибыли значит вы отдадите всю прибыль и ничего не заработаете.<br> 100% партнёру от суммы, значит вы всю сумму отдадите партнёру и ещё должны совершить обмен клиенту"),
            "classes": ("wide", "collapse"),
            "fields": (("partner_type", "percent"),),
        }),
        (_t("Финансы (USDT)"), {
            "classes": ("wide", "collapse"),
            "fields": (("balance_usdt", "total_profit_usdt",),
                       ("last_payout_at", "last_payout_amount_usdt"),),
        }),
        (_t("Баннер"), {
            "description": _t("PNG/JPG, ≤ 1 МБ, рекомендуемый размер 88×31"),
            "classes": ("wide", "collapse"),
            "fields": (("banner_dark_asset", "banner_dark_preview"),
                       ("banner_light_asset", "banner_light_preview"),),
        }),
        (_t("Прочее"), {
            "classes": ("wide", "collapse"),
            "fields": ("api_access", ("clicks_total", "last_click_at",), "title", "comment"),
        }),
    )

    @djadmin.action(description=_t("Зафиксировать выплату (обнулить баланс)"))
    def action_payout(self, request, queryset):
        now = timezone.now()
        updated = 0
        for obj in queryset:
            amount = obj.balance_usdt or Decimal("0")
            obj.last_payout_amount_usdt = amount
            obj.last_payout_at = now
            obj.balance_usdt = Decimal("0")
            obj.save(update_fields=["last_payout_amount_usdt", "last_payout_at", "balance_usdt"])
            updated += 1
        self.message_user(request, _t(f"Выплата зафиксирована, записей обновлено: {updated}"))

    actions = ("action_payout",)

    @djadmin.display(description=_t("Тёмный баннер"))
    def banner_dark_preview(self, obj):
        url = getattr(obj, "banner_dark_url", None)
        if callable(url): url = obj.banner_dark_url
        if url:
            return mark_safe(
                f'<img src="{url}" alt="" style="max-width:176px; max-height:62px; height:auto; width:auto; border:1px solid #ddd; border-radius:4px;">'
            )
        return "—"

    @djadmin.display(description=_t("Светлый баннер"))
    def banner_light_preview(self, obj):
        url = getattr(obj, "banner_light_url", None)
        if callable(url): url = obj.banner_light_url
        if url:
            return mark_safe(
                f'<img src="{url}" alt="" style="max-width:176px; max-height:62px; height:auto; width:auto; border:1px solid #ddd; border-radius:4px;">'
            )
        return "—"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name in ("banner_dark_asset", "banner_light_asset"):
            formfield.widget.attrs.update({"style": "width:30%; min-width: 32rem;"})
        return formfield

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        common_help = _t("PNG/JPG/SVG, ≤ 1 MB, рекомендуемый размер 88×31")
        for fname in ("banner_dark_asset", "banner_light_asset"):
            if fname not in form.base_fields:
                continue
            field = form.base_fields[fname]
            field.help_text = common_help
            w = field.widget
            if isinstance(w, RelatedFieldWidgetWrapper):
                w.can_add_related = False
                w.can_change_related = False
                w.can_delete_related = False
                w.can_view_related = False
                field.widget = w.widget
            if hasattr(field.widget, "attrs"):
                field.widget.attrs.setdefault("style", "")
                field.widget.attrs["style"] += "min-width:360px;width:100%;"
        return form


# ======================= Документы =======================
class DocumentAdminForm(TranslatableModelForm):
    template_to_insert = forms.ModelChoiceField(
        label=_t("Вставить из шаблона"),
        queryset=DocumentTemplate.objects.all().order_by("id"),
        required=False,
        help_text=_t("При сохранении заголовок и содержимое текущего языка будут полностью заменены текстом выбранного шаблона."),
    )
    template_overwrite = forms.BooleanField(
        label=_t("Перезаписать содержимое шаблоном"),
        required=False,
        help_text=_t("На форме изменения: если включено и выбран шаблон — текущий текст выбранного языка будет заменён."),
    )

    class Meta:
        model = Document
        fields = "__all__"

    def clean_slug(self):
        """Нормализуем пользовательский slug (оставляем unicode, вычищаем недопустимое)."""
        raw = (self.cleaned_data.get("slug") or "").strip()
        if not raw:
            # пустой допустим — автогенерится в save_model
            return ""
        normalized = slugify(raw, allow_unicode=True)
        return normalized

    def clean(self):
        """Проверяем уникальность slug в рамках выбранного языка формы."""
        cleaned = super().clean()
        slug = (cleaned.get("slug") or "").strip()
        if not slug:
            return cleaned  # автогенерация позже

        # язык формы кладётся в скрытое поле language_code (его устанавливает admin.get_form)
        lang = (cleaned.get("language_code") or "").strip() or getattr(settings, "LANGUAGE_CODE", "ru")

        qs = Document.objects.translated(language_code=lang, slug=slug)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError(
                {"slug": _t("Этот слаг уже используется для языка %(lang)s. Укажите другой.") % {"lang": lang.upper()}}
            )
        return cleaned


@djadmin.register(Document)
class DocumentAdmin(ParlerLanguageChipsMixin, TranslatableAdmin):
    save_on_top = True
    form = DocumentAdminForm

    list_display = ("title_col", "slug_col", "show_in_site", "updated_at")
    list_display_links = ("title_col",)
    # slug_current убираем из readonly, он больше не нужен в форме
    readonly_fields = ("updated_at", "placeholders_help",)

    fieldsets = (
        (_t("Содержимое"), {
            "classes": ("wide",),
            "fields": (
                ("title", "show_in_site"),
                "slug",  # <-- редактируемый slug
                "body",
                "template_to_insert",
                "template_overwrite",
                "placeholders_help",
            ),
        }),
        (_t("Служебное"), {
            "classes": ("wide",),
            "fields": ("updated_at",),
        }),
    )

    # ---------- язык формы и скрытое language_code ----------
    def get_form(self, request, obj=None, **kwargs):
        form_class = super().get_form(request, obj, **kwargs)

        lang = self.get_form_language(request, obj) or (get_language() or settings.LANGUAGE_CODE)
        setattr(form_class, "language_code", lang)

        if obj is not None and hasattr(obj, "set_current_language"):
            obj.set_current_language(lang)

        base = getattr(form_class, "base_fields", None)
        if base is not None:
            if "language_code" not in base:
                base["language_code"] = forms.CharField(required=False, widget=forms.HiddenInput)
            base["language_code"].initial = lang
            # На форме "добавить" скрываем чекбокс перезаписи
            if obj is None and "template_overwrite" in base:
                base["template_overwrite"].widget = forms.HiddenInput()

        return form_class

    # --------------------------------------------------------

    @djadmin.display(description=_t("Шаблоны"))
    def placeholders_help(self, obj=None):
        html = """
        <div style="font-size:13px;line-height:1.5">
            <p><strong>Вставляйте в текст документа:</strong></p>
            <ul style="margin:0 0 0 18px;padding:0">
                <li><code>[[DOMAIN]]</code> — реальный домен (из Настройки сайта: Домен)</li>
                <li><code>[[DOMAIN_VIEW]]</code> — отображаемый домен</li>
            </ul>
            <p style="margin-top:8px">
                Подстановка делается при рендере шаблона.
                В шаблоне используйте:
                <code>{% load placeholders %}</code> и
                <code>{% render_placeholders document.body %}</code>.
            </p>
        </div>
        """
        return mark_safe(html)

    def get_queryset(self, request):
        return super().get_queryset(request).translated()

    @djadmin.display(description=_t("Заголовок"))
    def title_col(self, obj: Document):
        return obj.safe_translation_getter("title", any_language=True) or f"#{obj.pk}"

    @djadmin.display(description="Slug")
    def slug_col(self, obj: Document):
        return obj.safe_translation_getter("slug", any_language=True) or "—"

    def render_change_form(self, request, context, *args, **kwargs):
        # чтобы form/чипы и Parler брали один язык
        self.request = request
        return super().render_change_form(request, context, *args, **kwargs)

    def save_model(self, request, obj: Document, form, change):
        """
        1) Сохраняем перевод с учётом активного языка (как и раньше).
        2) Если выбран шаблон — заголовок берём из get_kind_display(), тело заменяем на body шаблона.
        3) Если slug пуст — по умолчанию берём его из kind шаблона; если шаблон не выбран — из title.
           Обеспечиваем уникальность slug в рамках текущего языка.
        4) Перед сохранением slug — нормализуем через slugify (на случай, если админ руками ввёл «не то»).
        """
        lang = self.get_form_language(request, obj) or (get_language() or settings.LANGUAGE_CODE)
        if hasattr(obj, "set_current_language"):
            obj.set_current_language(lang)

        tpl: DocumentTemplate | None = None
        tpl_id = None
        if form is not None and hasattr(form, "cleaned_data"):
            tpl = form.cleaned_data.get("template_to_insert")  # ModelChoiceField -> instance
            tpl_overwrite = bool(form.cleaned_data.get("template_overwrite"))
        else:
            tpl_overwrite = False

        # Если выбран шаблон:
        if tpl:
            # Заголовок для текущего языка берём из label'а choices (локализованного)
            obj.title = str(tpl.get_kind_display()).strip()
            # Текст заменяем полностью (на форме создания — всегда; на форме изменения — если чекбокс отмечен)
            if (not change) or tpl_overwrite:
                obj.body = tpl.body or ""

        # --- slug: если пуст, строим по умолчанию ---
        raw_slug = (obj.slug or "").strip()

        if not raw_slug:
            # приоритет: если есть шаблон — slug из kind; иначе — из title
            base = tpl.kind if tpl else slugify((obj.title or "").strip()) or "doc"
        else:
            # админ мог ввести руками — нормализуем
            base = slugify(raw_slug) or "doc"

        # Уникальность slug в рамках языка
        unique_slug = base
        i = 2
        while Document.objects.translated(language_code=lang, slug=unique_slug).exclude(pk=obj.pk).exists():
            unique_slug = f"{base}-{i}"
            i += 1
        obj.slug = unique_slug

        super().save_model(request, obj, form, change)

    def add_view(self, request, form_url="", extra_context=None):
        # На странице создания фиксируем язык формы на LANGUAGE_CODE
        if hasattr(request, "session"):
            request.session["PARLER_CURRENT_LANGUAGE"] = getattr(settings, "LANGUAGE_CODE", "ru")
        return super().add_view(request, form_url, extra_context)


try:
    djadmin.site.unregister(Site)
except NotRegistered:
    pass
