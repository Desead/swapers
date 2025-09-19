from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.utils import timezone
from django.db.models import Sum
from axes.utils import reset as axes_reset
from .models import SiteSetup
from app_main.models_security import BlocklistEntry
from .utils.telegram import send_telegram_message
from .utils.audit import diff_sitesetup, format_telegram_message
from axes.models import AccessAttempt, AccessFailureLog
from django.contrib import admin
from django.conf import settings
from django.utils.translation import get_language, gettext_lazy as _
from django.utils.safestring import mark_safe
from django.urls import reverse
from django.shortcuts import redirect
from django.db import models
from parler.admin import TranslatableAdmin
from parler.forms import TranslatableModelForm
from django.core.exceptions import FieldDoesNotExist

# + твои импорты моделей/утилит:
# from .models import SiteSetup
# from .admin_utils import diff_sitesetup, format_telegram_message, send_telegram_message


User = get_user_model()


# ======================= Пользователи =======================

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


# ======================= Настройки сайта (SiteSetup) =======================
class SiteSetupAdminForm(TranslatableModelForm):
    # Рисуем чекбоксы вместо JSON-текста
    site_enabled_languages = forms.MultipleChoiceField(
        choices=(),  # выставим в __init__
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=_("Языки, показываемые на сайте"),
        help_text=_("Выберите языки, которые должны быть видимы на сайте (переключатель, hreflang)."),
    )

    class Meta:
        model = SiteSetup
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # choices берем из настроек
        self.fields["site_enabled_languages"].choices = list(
            getattr(settings, "LANGUAGES", (("ru", "Russian"),))
        )

        inst = kwargs.get("instance")
        if inst is not None:
            initial = inst.site_enabled_languages or inst.get_enabled_languages()
        else:
            # форма "добавить" нам не нужна, но пусть работает
            default = (getattr(settings, "LANGUAGE_CODE", "ru") or "ru").split("-")[0].lower()
            initial = [default]
        self.fields["site_enabled_languages"].initial = initial

    def clean_site_enabled_languages(self):
        langs = self.cleaned_data.get("site_enabled_languages") or []
        # нормализуем: только известные языки, в нижнем регистре, без дублей
        known = [code for code, _ in getattr(settings, "LANGUAGES", ())]
        known_set = {c.lower() for c in known}
        out, seen = [], set()
        for c in langs:
            cc = (c or "").lower()
            if cc in known_set and cc not in seen:
                out.append(cc)
                seen.add(cc)
        return out


@admin.register(SiteSetup)
class SiteSetupAdmin(TranslatableAdmin, admin.ModelAdmin):
    # Вкладки Parler
    change_form_template = "admin/parler/change_form.html"
    save_on_top = True
    form = SiteSetupAdminForm

    formfield_overrides = {
        models.URLField: {"assume_scheme": "https"},
    }

    # из settings.LANGUAGES (какие вообще есть в проекте)
    SITE_LANG_CHOICES = tuple(getattr(settings, "LANGUAGES", (("ru", "Russian"),)))

    readonly_fields = (
        "updated_at",
        "og_image_width", "og_image_height",
        "og_image_preview", "twitter_image_preview",
        "translation_matrix",
        "language_toolbar",  # ← панель языков вверху формы
    )

    fieldsets = (
        (_("Главная страница"), {
            "classes": ("wide",),
            "fields": ("main_h1", "main_subtitle", ("domain", "domain_view"), "maintenance_mode"),
        }),
        (_("Перевод на различные языки"), {
            "classes": ("wide", "collapse"),
            "fields": ("language_toolbar", "site_enabled_languages", "translation_matrix"),
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
            "fields": ("head_inject_html", "xml_export_path", ("telegram_bot_token", "telegram_chat_id")),
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
                ("contact_label_clients", "contact_email_clients"),
                ("contact_label_partners", "contact_email_partners"),
                ("contact_label_general", "contact_email_general"),
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
                ("jsonld_organization", "jsonld_website"),
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
            "fields": ("updated_at", ),
        }),
    )

    # ---------- Язык формы ----------
    def get_form_language(self, request, obj=None):
        """
        Текущий язык вкладки/формы (Parler ориентируется на это).
        При клике на чип мы идём на ?language=xx, здесь это подхватываем.
        """
        lang = request.GET.get("language")
        if lang:
            request.session["PARLER_CURRENT_LANGUAGE"] = lang
            return lang
        return request.session.get("PARLER_CURRENT_LANGUAGE") or (get_language() or settings.LANGUAGE_CODE)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # --- render site_enabled_languages as checkboxes ---
        if "site_enabled_languages" in form.base_fields:
            choices = list(getattr(settings, "LANGUAGES", ()))
            # текущее значение как initial
            initial = []
            if obj and isinstance(getattr(obj, "site_enabled_languages", None), list):
                valid = {c for c, _ in choices}
                initial = [c for c in obj.site_enabled_languages if c in valid]

            form.base_fields["site_enabled_languages"] = forms.MultipleChoiceField(
                required=False,
                choices=choices,
                widget=forms.CheckboxSelectMultiple,
                initial=initial,
                label=form.base_fields.get("site_enabled_languages").label or _("Языки, показывать на сайте"),
                help_text=_("Отмеченные языки появятся в переключателе языков на сайте."),
            )

        # Активируем язык на объекте, чтобы .safe_translation_getter(...) и формы
        # показывали нужную локаль без сюрпризов.
        try:
            lang = self.get_form_language(request)
            if obj is not None and hasattr(obj, "set_current_language"):
                obj.set_current_language(lang)
        except Exception:
            pass
        return form

    @admin.display(description=_("Редактировать перевод"))
    def language_toolbar(self, obj):
        langs = [code for code, _ in self.SITE_LANG_CHOICES]
        # определяем текущий язык так же, как делает форма
        if hasattr(self, "request") and self.request is not None:
            cur = (self.get_form_language(self.request, obj) or settings.LANGUAGE_CODE).lower()
        else:
            cur = (get_language() or settings.LANGUAGE_CODE).lower()

        chips = []
        base_style = (
            "display:inline-block;margin:2px 6px 2px 0;padding:4px 10px;border-radius:999px;"
            "font-size:12px;text-decoration:none;border:1px solid #ddd;"
        )
        for code in langs:
            is_cur = (code.lower() == cur)
            style = base_style + (
                "background:#2e7d32;color:#fff;border-color:#2e7d32;" if is_cur
                else "background:#f5f5f5;color:#333;"
            )
            chips.append(f'<a href="?language={code}" style="{style}">{code.upper()}</a>')
        return mark_safe("".join(chips))

    # ---------- Таблица/статус переводов (оставляем как было) ----------
    def _translated_field_names(self, obj):
        try:
            return list(getattr(obj._parler_meta, "_fields_to_model", {}).keys())
        except Exception:
            return []

    def _human_field_label(self, obj, fname: str) -> str:
        """
        Возвращает человекочитаемый ярлык поля:
        - сначала пытаемся достать verbose_name с основного объекта;
        - если поля там нет, берём verbose_name с translation-модели Parler;
        - в крайнем случае — возвращаем имя поля.
        """
        try:
            f = obj._meta.get_field(fname)
            return getattr(f, "verbose_name", fname) or fname
        except FieldDoesNotExist:
            pass
        except Exception:
            # на случай неожиданных ситуаций не падаем
            pass

        # Поле не на основной модели -> пробуем на translation-модели Parler
        try:
            tr_model = obj._parler_meta.get_model_by_field(fname)
            f = tr_model._meta.get_field(fname)
            return getattr(f, "verbose_name", fname) or fname
        except Exception:
            return fname

    @admin.display(description=_("Матрица переводов"))
    def translation_matrix(self, obj):
        if not obj:
            return "—"
        fields = self._translated_field_names(obj)
        if not fields:
            return _("Нет переводимых полей.")
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
            name_cell = (
                f'<td style="padding:6px 10px;white-space:nowrap;">'
                f'{verbose}<br>'
                f'</td>'
            )
            rows.append(f'<tr>{name_cell}{"".join(tds)}</tr>')
        table = (
            '<div style="overflow:auto;border:1px solid #eee;border-radius:8px;">'
            '<table style="width:100%;border-collapse:collapse;font-size:12px;">'
            f'<thead><tr><th style="padding:6px 10px;text-align:left;">{_("Поле")}</th>{ths}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody>'
            '</table>'
            '<div style="padding:6px 0 0 2px;font-size:11px;color:#666;">'
            f'✓ — {_("есть значение")}, • — {_("пусто/нет перевода")}'
            '</div>'
            '</div>'
        )
        return mark_safe(table)

    # ---------- Прочее оставляем как было ----------
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = SiteSetup.get_solo()
        url = reverse("admin:app_main_sitesetup_change", args=[obj.pk])
        return redirect(url)

    def render_change_form(self, request, context, *args, **kwargs):
        # сохраним request, чтобы language_toolbar знал текущий язык
        self.request = request
        scheme = "https" if not settings.DEBUG else "http"
        domain = request.get_host()
        robots_url = f"{scheme}://{domain}{reverse('robots_txt')}"
        form = context.get("adminform").form
        if "robots_txt" in form.fields:
            base_help = form.fields["robots_txt"].help_text or ""
            form.fields["robots_txt"].help_text = mark_safe(f'{base_help}<br><a href="{robots_url}" target="_blank">↗ robots.txt</a>')
        return super().render_change_form(request, context, *args, **kwargs)

    @admin.display(description=_("Превью OG"))
    def og_image_preview(self, obj: SiteSetup):
        try:
            if obj and obj.og_image and obj.og_image.url:
                return mark_safe(f'<img src="{obj.og_image.url}" style="max-width:360px;height:auto;border:1px solid #ddd;border-radius:4px;">')
        except Exception:
            pass
        return "—"

    @admin.display(description=_("Превью Twitter"))
    def twitter_image_preview(self, obj: SiteSetup):
        try:
            if obj and obj.twitter_image and obj.twitter_image.url:
                return mark_safe(f'<img src="{obj.twitter_image.url}" style="max-width:360px;height:auto;border:1px solid #ddd;border-radius:4px;">')
        except Exception:
            pass
        return "—"

    def save_model(self, request, obj: SiteSetup, form, change):
        # --- гарантируем, что всегда сохранится хотя бы один язык ---
        allowed = [c.lower() for c, _ in getattr(settings, "LANGUAGES", ())]
        def _normalize(code: str | None) -> str | None:
            if not code:
                return None
            c = code.lower().replace("_", "-")
            if c in allowed:
                return c
            base = c.split("-", 1)[0]
            # ищем близкий вариант из allowed (ru ↔ ru-ru и т.п.)
            for a in allowed:
                if a == base or a.split("-", 1)[0] == base:
                    return a
            return None

        # берём выбранные из формы (поддерживаем оба варианта поля),
        # иначе — текущее значение на объекте
        selected = None
        if form is not None and hasattr(form, "cleaned_data"):
            selected = (
                form.cleaned_data.get("site_enabled_languages")
                or form.cleaned_data.get("site_enabled_languages_list")
            )
        if selected is None:
            selected = obj.site_enabled_languages or []

        # нормализуем, фильтруем и убираем дубли
        norm = []
        seen = set()
        for code in selected:
            n = _normalize(code)
            if n and n not in seen:
                norm.append(n)
                seen.add(n)

        # если пусто — подставляем дефолтный
        if not norm:
            default_norm = _normalize(getattr(settings, "LANGUAGE_CODE", ""))
            if not default_norm and allowed:
                default_norm = allowed[0]
            if default_norm:
                norm = [default_norm]

        obj.site_enabled_languages = norm
        # --- /гарантия одного языка ---

        # дальше — твоя существующая логика (diff, телеграм и т.д.)
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
        # На всякий случай подгрузим ресурсы Parler (если шаблон уже их не подключил)
        js = ("admin/js/jquery.init.js", "parler/js/admin/parler.js")
        css = {"all": ("parler/css/admin/parler.css",)}


# ======================= Чёрный список =======================

@admin.register(BlocklistEntry)
class BlocklistEntryAdmin(admin.ModelAdmin):
    list_display = ("user_name_view", "email", "ip_address", "is_active", "reason", "created_at")
    list_filter = ("is_active",)
    search_fields = ("email", "ip_address", "user__email", "reason")
    actions = ["activate_selected", "deactivate_selected"]

    @admin.action(description=_("Активировать выбранные"))
    def activate_selected(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description=_("Деактивировать выбранные"))
    def deactivate_selected(self, request, queryset):
        queryset.update(is_active=False)

    @admin.display(description=_("Пользователь"))
    def user_name_view(self, obj):
        return getattr(getattr(obj, "user", None), "email", "—")


# ======================= Axes: Попытки доступа =======================

try:
    admin.site.unregister(AccessAttempt)
except admin.sites.NotRegistered:
    pass


def _get_cooloff():
    """Возвращает timedelta «окна охлаждения» Axes (значение либо результат коллбэка)."""
    cooloff = getattr(settings, "AXES_COOLOFF_TIME", None)
    if callable(cooloff):
        cooloff = cooloff()
    return cooloff


def _axes_param_sets():
    """
    Нормализуем AXES_LOCKOUT_PARAMETERS к списку множеств:
    [["username", "ip_address"], "ip_address"] -> [{"username","ip_address"}, {"ip_address"}]
    """
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
    """
    Совместимая обёртка над axes.reset:
    - в одних версиях ожидается ip_address=..., в других ip=...
    - часть параметров может отсутствовать в сигнатуре → отбрасываем лишнее
    """
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


@admin.register(AccessAttempt)
class AccessAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "ip_address",
        "username",
        "failures_since_start",
        "lock_key_type",
        "is_blocked_now",
        "path_info_short",
        "user_agent_short",
    )
    search_fields = ("ip_address", "username", "path_info", "user_agent")
    list_filter = ("ip_address",)
    actions = ("reset_lock_ip", "reset_lock_username", "reset_lock_both")

    @admin.display(description=_("Тип блокировки"))
    def lock_key_type(self, obj: AccessAttempt):
        limit = int(getattr(settings, "AXES_FAILURE_LIMIT", 5) or 5)
        param_sets = _axes_param_sets()

        if {"username", "ip_address"} in param_sets and obj.username and obj.ip_address:
            pair_total = (
                    AccessAttempt.objects
                    .filter(username=obj.username, ip_address=obj.ip_address)
                    .aggregate(s=Sum("failures_since_start"))["s"] or 0
            )
            if pair_total >= limit:
                return _("Логин + IP")

        if {"ip_address"} in param_sets and obj.ip_address:
            ip_total = (
                    AccessAttempt.objects
                    .filter(ip_address=obj.ip_address)
                    .aggregate(s=Sum("failures_since_start"))["s"] or 0
            )
            if ip_total >= limit:
                return _("IP")

        if {"username"} in param_sets and obj.username:
            user_total = (
                    AccessAttempt.objects
                    .filter(username=obj.username)
                    .aggregate(s=Sum("failures_since_start"))["s"] or 0
            )
            if user_total >= limit:
                return _("Логин")

        for s in param_sets:
            parts = []
            if "username" in s:
                parts.append(_("Логин"))
            if "ip_address" in s:
                parts.append(_("IP"))
            if "user_agent" in s:
                parts.append(_("User-Agent"))
            if parts:
                return " + ".join(parts)
        return "—"

    @admin.display(boolean=True, description=_("Заблокирован?"))
    def is_blocked_now(self, obj):
        cooloff = _get_cooloff()
        if not cooloff:
            return False

        limit = int(getattr(settings, "AXES_FAILURE_LIMIT", 5) or 5)
        now = timezone.now()
        k = self.lock_key_type(obj)

        if k == _("Логин + IP"):
            pair_total = (
                    AccessAttempt.objects
                    .filter(username=obj.username, ip_address=obj.ip_address)
                    .aggregate(s=Sum("failures_since_start"))["s"] or 0
            )
            if pair_total >= limit:
                last = _last_failure_dt_for(obj, "Логин + IP")
                return bool(last and now < last + cooloff)
            return False

        if k == _("IP"):
            ip_total = (
                    AccessAttempt.objects
                    .filter(ip_address=obj.ip_address)
                    .aggregate(s=Sum("failures_since_start"))["s"] or 0
            )
            if ip_total >= limit:
                last = _last_failure_dt_for(obj, "IP")
                return bool(last and now < last + cooloff)
            return False

        if k == _("Логин"):
            user_total = (
                    AccessAttempt.objects
                    .filter(username=obj.username)
                    .aggregate(s=Sum("failures_since_start"))["s"] or 0
            )
            if user_total >= limit:
                last = _last_failure_dt_for(obj, "Логин")
                return bool(last and now < last + cooloff)
            return False

        return False

    @admin.display(description=_("Путь"))
    def path_info_short(self, obj):
        return (obj.path_info or "")[:80]

    @admin.display(description=_("User-Agent"))
    def user_agent_short(self, obj):
        ua = obj.user_agent or ""
        return (ua[:80] + "…") if len(ua) > 80 else ua

    def _action_guard_and_reset(self, request, queryset, expected_type: str, do_reset):
        done = 0
        skipped = 0
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

        msg = _("Снято блокировок: %(done)s. Пропущено: %(skipped)s.") % {"done": done, "skipped": skipped}
        self.message_user(request, msg)

    @admin.action(description=_("Снять блокировку по IP"))
    def reset_lock_ip(self, request, queryset):
        def _do(o):
            if o.ip_address:
                _axes_reset_safe(ip=o.ip_address)

        self._action_guard_and_reset(request, queryset, expected_type=_("IP"), do_reset=_do)

    @admin.action(description=_("Снять блокировку по логину"))
    def reset_lock_username(self, request, queryset):
        def _do(o):
            if o.username:
                _axes_reset_safe(username=o.username)

        self._action_guard_and_reset(request, queryset, expected_type=_("Логин"), do_reset=_do)

    @admin.action(description=_("Снять блокировку по логину+IP"))
    def reset_lock_both(self, request, queryset):
        def _do(o):
            if o.ip_address or o.username:
                _axes_reset_safe(ip=o.ip_address, username=o.username)

        self._action_guard_and_reset(request, queryset, expected_type=_("Логин + IP"), do_reset=_do)
