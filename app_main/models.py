from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.utils import timezone
from django.core.validators import validate_email, RegexValidator, MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.conf import settings
from django.contrib.sites.models import Site
from django.utils.translation import gettext_lazy as _  # lazy — для verbose_name/help_text
from django.utils.translation import gettext as _gettext  # runtime — для __str__ и сообщений
from django.core.files.images import get_image_dimensions


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError(_("Email обязателен"))
        email = self.normalize_email(email)
        validate_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("is_active", True)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Суперпользователь должен иметь is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Суперпользователь должен иметь is_superuser=True."))
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    # аутентификация
    email = models.EmailField(verbose_name=_("Email"), unique=True, db_index=True)
    first_name = models.CharField(verbose_name=_("Имя"), max_length=150, blank=True)
    last_name = models.CharField(verbose_name=_("Фамилия"), max_length=150, blank=True)
    phone = models.CharField(verbose_name=_("Телефон"), max_length=32, blank=True)
    company = models.CharField(verbose_name=_("Компания"), max_length=255, blank=True)

    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    # партнёрка
    referred_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="referrals", verbose_name=_("Кто привёл")
    )
    referral_code = models.CharField(verbose_name=_("Партнёрский код"), max_length=16, unique=True, blank=True)
    count = models.PositiveIntegerField(verbose_name=_("Партнёров привлечено"), default=0)
    balance = models.DecimalField(verbose_name=_("Партнёрский баланс, $"), max_digits=12, decimal_places=2, default=0)

    # Когда впервые увидели реф-код (для атрибуции)
    referral_first_seen_at = models.DateTimeField(
        verbose_name=_("Первый визит по партнёрской ссылке"),
        null=True, blank=True,
        help_text=_("Дата и время первого визита с реферальным кодом."),
    )
    # Сколько времени прошло до регистрации
    referral_signup_delay = models.DurationField(
        verbose_name=_("Задержка до регистрации"),
        null=True, blank=True,
        help_text=_("Разница между первым визитом по реф-ссылке и моментом регистрации."),
    )

    # предпочитаемый язык пользователя
    language = models.CharField(
        verbose_name=_("Язык общения"),
        max_length=8,
        choices=[(code, name) for code, name in settings.LANGUAGES],
        default=(settings.LANGUAGE_CODE.split("-")[0] if hasattr(settings, "LANGUAGE_CODE") else "ru"),
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = _("Пользователь")
        verbose_name_plural = _("Пользователи")
        indexes = [
            models.Index(fields=["referred_by", "date_joined"], name="user_ref_by_date_idx"),
            models.Index(fields=["date_joined"], name="user_joined_idx"),
        ]
        # ВАЖНО: оставить на английском — это имя уйдёт в БД при миграциях
        permissions = [
            ("export_users", "Can export users"),
            ("view_finance", "Can view finance dashboards"),
        ]

    def __str__(self):
        return self.email


RESERVED_ADMIN_PREFIXES = {"static", "media", "api", "accounts", "rosetta"}


# defaults for JSON-LD (module-level callables; держи их ВЫШЕ класса)
def default_jsonld_org():
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Swapers",
        "url": "https://swap.com",
        "logo": "https://swap.com/static/branding/logo.png",
        "sameAs": [],
        "contactPoint": [{
            "@type": "ContactPoint",
            "contactType": "customer support",
            "email": "support@swap.com"
        }],
    }


def default_jsonld_website():
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "Swapers",
        "url": "https://swap.com",
        "inLanguage": "ru",
    }


class SiteSetup(models.Model):
    """Singleton with site settings."""
    singleton = models.CharField(max_length=16, unique=True, default="main", editable=False)

    # домен и отображаемое имя сайта
    domain = models.CharField(
        verbose_name=_("Домен (без http/https)"),
        max_length=253,
        default="swap.com",
        help_text=_("Например: example.com или localhost (без http/https)."),
        validators=[RegexValidator(
            regex=r"^(localhost|(?:(?!-)[A-Za-z0-9-]{1,63}(?<!-)\.)+[A-Za-z]{2,63})$",
            message=_("Введите корректное доменное имя, например: example.com"),
        )],
    )
    domain_view = models.CharField(
        verbose_name=_("Отображаемое имя сайта"),
        max_length=100,
        default="Swapers",
        help_text=_('Название для заголовков/письма и т.п., например: "Swapers".'),
    )

    admin_path = models.CharField(
        verbose_name=_("Путь к админке"),
        max_length=50,
        default="admin",
        validators=[RegexValidator(
            regex=r"^[a-z0-9-]+$",
            message=_("Разрешены только маленькие латинские буквы, цифры и дефис"),
        )],
        help_text=_("Например: supera-dmin"),
    )
    otp_issuer = models.CharField(
        verbose_name=_("Название сервиса для 2FA"),
        max_length=64,
        default="Swapers",
        validators=[RegexValidator(
            regex=r"^[A-Za-z0-9 ._-]+$",
            message=_("Допустимы латиница, цифры, пробел, точка, дефис, подчёркивание."),
        )],
        help_text=_('Отобразится в приложении-аутентификаторе (например: "Swapers").'),
    )

    admin_session_timeout_min = models.PositiveIntegerField(
        verbose_name=_("Автовыход из админки, минут"),
        default=10,
        help_text=_("Через сколько минут бездействия разлогинивать из админки. "
                    "0 — не разлогинивать по простою (сессия живёт до закрытия браузера)."),
    )

    # --- robots.txt и индексация ---
    robots_txt = models.TextField(
        verbose_name=_("Содержимое robots.txt"),
        help_text=_(
            "Текст, который будет отдан по /robots.txt. Строка "
            "Sitemap: https://HOST/sitemap.xml позже будет добавлена автоматически."
        ),
        blank=True,
        default="User-agent: *\nDisallow:\n",
    )
    block_indexing = models.BooleanField(
        verbose_name=_("Запретить индексацию всего сайта"),
        help_text=_(
            "Если включено, robots.txt будет отдавать 'Disallow: /', а во всех ответах "
            "будет заголовок 'X-Robots-Tag: noindex, nofollow'"
        ),
        default=False,
    )

    # — для инвалидации кеша/Last-Modified —
    updated_at = models.DateTimeField(_("Обновлено"), auto_now=True)

    # --- [1] SEO по умолчанию ---
    seo_default_title = models.CharField(
        verbose_name=_("SEO: заголовок по умолчанию (title)"),
        max_length=255,
        blank=True,
        default="Swapers — быстрый и безопасный обмен криптовалют онлайн",
        help_text=_("Используется как базовый title, если страница не переопределяет его."),
    )
    seo_default_description = models.TextField(
        verbose_name=_("SEO: описание по умолчанию (meta description)"),
        blank=True,
        default=(
            "Онлайн-обменник криптовалют. Мгновенные сделки, прозрачные курсы, фиксированная комиссия. "
            "Поддержка Bitcoin, Ethereum и популярных стейблкоинов: USDT, USDC, DAI и другие."
        ),
        help_text=_("Используется как базовое описание, если страница не переопределяет его."),
    )
    seo_default_keywords = models.TextField(
        verbose_name=_("SEO: ключевые слова по умолчанию (meta keywords)"),
        blank=True,
        default="обменник, криптовалюта, обмен криптовалют, bitcoin, ethereum, usdt, usdc, dai, обмен онлайн",
        help_text=_("Опционально. Может не использоваться поисковиками, но полезно для некоторых интеграций."),
    )

    # --- [2] Open Graph / Twitter / Canonical / hreflang / JSON-LD ---
    og_enabled = models.BooleanField(
        verbose_name=_("Включить Open Graph"),
        default=True,
        help_text=_("Если выключено, OG-теги выводиться не будут."),
    )
    og_type_default = models.CharField(
        verbose_name=_("OG: тип по умолчанию"),
        max_length=20,
        choices=[("website", "website"), ("article", "article")],
        default="website",
    )
    og_title = models.CharField(
        verbose_name=_("OG: заголовок по умолчанию"),
        max_length=255,
        blank=True,
        default="Swapers — быстрый и безопасный обмен криптовалют онлайн",
        help_text=_("Используется, если страница не задаёт свой OG-заголовок."),
    )
    og_description = models.TextField(
        verbose_name=_("OG: описание по умолчанию"),
        blank=True,
        default="Мгновенный обмен BTC, ETH, USDT и других активов. Прозрачные курсы, фиксированная комиссия, 2FA защита.",
    )
    og_image = models.ImageField(
        verbose_name=_("OG: изображение по умолчанию (1200×630)"),
        upload_to="seo/",
        blank=True, null=True,
        help_text=_("Используется, если страница не задала картинку. Желательно ~1200×630, до 5 MB."),
        width_field="og_image_width",
        height_field="og_image_height",
    )
    og_image_width = models.PositiveIntegerField(editable=False, default=0)
    og_image_height = models.PositiveIntegerField(editable=False, default=0)
    og_image_alt = models.CharField(
        verbose_name=_("OG: alt у изображения"),
        max_length=255,
        blank=True,
        default="Логотип Swapers и обмен криптовалют онлайн",
    )
    og_locale_default = models.CharField(
        verbose_name=_("OG: локаль по умолчанию"),
        max_length=10,
        default="ru_RU",
        help_text=_("Например: ru_RU или en_US."),
    )
    og_locale_alternates = models.CharField(
        verbose_name=_("OG: альтернативные локали (через запятую)"),
        max_length=100,
        blank=True,
        default="en_US",
        help_text=_("Например: en_US,uk_UA. Будут выведены с og:locale:alternate."),
    )

    twitter_cards_enabled = models.BooleanField(
        verbose_name=_("Включить Twitter Cards"),
        default=True,
    )
    twitter_card_type = models.CharField(
        verbose_name=_("Twitter: тип карточки"),
        max_length=32,
        choices=[("summary_large_image", "summary_large_image"), ("summary", "summary")],
        default="summary_large_image",
    )
    twitter_site = models.CharField(
        verbose_name=_("Twitter: @site (без @)"),
        max_length=50, blank=True,
        default="",
        help_text=_("Имя аккаунта проекта в X/Twitter, без @."),
    )
    twitter_creator = models.CharField(
        verbose_name=_("Twitter: @creator (без @)"),
        max_length=50, blank=True,
        default="",
        help_text=_("Личный аккаунт автора/редактора, без @ (опционально)."),
    )
    twitter_image = models.ImageField(
        verbose_name=_("Twitter: изображение по умолчанию"),
        upload_to="seo/",
        blank=True, null=True,
        help_text=_("Если не задано — будет использовано OG-изображение."),
    )

    use_https_in_meta = models.BooleanField(
        verbose_name=_("https в canonical/OG URL"),
        default=False,
        help_text=_("Если выключено — будет использоваться http Объязательно включить на проде!"),
    )

    hreflang_enabled = models.BooleanField(
        verbose_name=_("Включить hreflang ссылки"),
        default=True,
        help_text=_("Включает генерацию ссылок alternates для RU/EN."),
    )
    hreflang_xdefault = models.CharField(
        verbose_name=_("hreflang: x-default язык"),
        max_length=8,
        default="ru",
        help_text=_("Например: ru или en — какая версия по умолчанию для поисковика."),
    )

    jsonld_enabled = models.BooleanField(
        verbose_name=_("Включить JSON-LD (schema.org)"),
        default=True,
    )
    jsonld_organization = models.JSONField(
        verbose_name=_("JSON-LD: Organization (дефолт)"),
        blank=True, null=True,
        default=default_jsonld_org,
        help_text=_("JSON объект schema.org/Organization для главной/всего сайта."),
    )
    jsonld_website = models.JSONField(
        verbose_name=_("JSON-LD: WebSite (дефолт)"),
        blank=True, null=True,
        default=default_jsonld_website,
        help_text=_("JSON объект schema.org/WebSite."),
    )

    # --- [3] Техработы ---
    maintenance_mode = models.BooleanField(
        verbose_name=_("Технические работы"),
        default=False,
        help_text=_("Если включено — пользователи увидят страницу техработ. По умолчанию выключено."),
    )

    # --- [4] График работы (UTC) ---
    open_time_mon = models.TimeField(_("Понедельник: начало (UTC)"), default="07:00")
    close_time_mon = models.TimeField(_("Понедельник: конец (UTC)"), default="19:00")
    open_time_tue = models.TimeField(_("Вторник: начало (UTC)"), default="07:00")
    close_time_tue = models.TimeField(_("Вторник: конец (UTC)"), default="19:00")
    open_time_wed = models.TimeField(_("Среда: начало (UTC)"), default="07:00")
    close_time_wed = models.TimeField(_("Среда: конец (UTC)"), default="19:00")
    open_time_thu = models.TimeField(_("Четверг: начало (UTC)"), default="07:00")
    close_time_thu = models.TimeField(_("Четверг: конец (UTC)"), default="19:00")
    open_time_fri = models.TimeField(_("Пятница: начало (UTC)"), default="07:00")
    close_time_fri = models.TimeField(_("Пятница: конец (UTC)"), default="19:00")
    open_time_sat = models.TimeField(_("Суббота: начало (UTC)"), default="09:00")
    close_time_sat = models.TimeField(_("Суббота: конец (UTC)"), default="17:00")
    open_time_sun = models.TimeField(_("Воскресенье: начало (UTC)"), default="09:00")
    close_time_sun = models.TimeField(_("Воскресенье: конец (UTC)"), default="17:00")

    # --- [5] Список стейблкоинов ---
    stablecoins = models.TextField(
        verbose_name=_("Список стейблкоинов"),
        blank=True,
        default="USDT, USDC, DAI, TUSD, FDUSD, PYUSD, USDP, GUSD, EURT, EURC, FRAX",
        help_text=_("Через запятую, тикеры в верхнем регистре (например: USDT, USDC, DAI)."),
    )

    # --- [6] Путь для будущей XML-выгрузки курсов ---
    xml_export_path = models.CharField(
        verbose_name=_("Путь для XML-выгрузки"),
        max_length=64,
        default="xml_export",
        validators=[RegexValidator(regex=r"^[a-z0-9/_-]+$", message=_("Разрешены строчные латинские буквы, цифры, '-', '_' и '/'. Без ведущего слеша."))],
        help_text=_("Будущая точка выдачи XML, например «xml_export» → /xml_export"),
    )

    # --- [7] Брендинг ---
    logo = models.ImageField(
        verbose_name=_("Логотип"),
        upload_to="branding/",
        blank=True, null=True,
        help_text=_("PNG/SVG; будет использоваться в шапке/мета."),
    )
    favicon = models.ImageField(
        verbose_name=_("Favicon"),
        upload_to="branding/",
        blank=True, null=True,
        help_text=_("PNG/ICO 32×32 или 48×48."),
    )

    # --- [8] Комиссия обменника ---
    fee_percent = models.DecimalField(
        verbose_name=_("Комиссия обменника, %"),
        max_digits=5, decimal_places=2,
        default=0.50,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=_("Процент с каждой сделки (0–100)."),
    )

    # --- [9] Вставка в head ---
    head_inject_html = models.TextField(
        verbose_name=_("HTML-код для вставки в head"),
        blank=True,
        help_text=_("Счётчики/метрики и т.п. Вставляется как есть на всех страницах."),
    )

    # --- [10] Почтовые настройки ---
    email_from = models.EmailField(
        verbose_name=_("E-mail отправителя (FROM)"),
        blank=True,
        help_text=_("Например: no-reply@swap.com"),
    )
    email_host = models.CharField(_("SMTP host"), max_length=255, blank=True, default="smtp.mail.ru")
    email_port = models.PositiveIntegerField(_("SMTP port"), default=587)
    email_host_user = models.CharField(_("SMTP user"), max_length=255, blank=True, default="")
    email_host_password = models.CharField(_("SMTP password"), max_length=255, blank=True, default="")
    email_use_tls = models.BooleanField(_("Использовать TLS"), default=True)
    email_use_ssl = models.BooleanField(_("Использовать SSL"), default=False)

    # --- [11] Интеграция с Telegram ---
    telegram_bot_token = models.CharField(
        verbose_name=_("Telegram Bot Token"),
        max_length=255, blank=True,
        default="",
        help_text=_("Токен бота для уведомлений (хранится как есть)."),
    )
    telegram_chat_id = models.CharField(
        verbose_name=_("Telegram Chat/Channel ID"),
        max_length=64, blank=True,
        default="",
        help_text=_("ID  канала/чата, куда слать служебные уведомления. Чтобы узнать ID запустите бота: @username_to_id_bot"),
    )

    # --- [12] Тексты на главную ---
    main_h1 = models.CharField(
        verbose_name=_("H1 на главной"),
        max_length=200,
        default="Мгновенный обмен криптовалют онлайн",
    )
    main_subtitle = models.TextField(
        verbose_name=_("Подзаголовок на главной"),
        blank=True,
        default="Обменивайте Bitcoin, Ethereum и стейблкоины быстро, безопасно и по честному курсу.",
    )

    # --- [13] Контакты и соцсети ---
    # названия (редактируемые) для трёх почтовых блоков
    contact_label_clients = models.CharField(
        verbose_name=_("Заголовок: почта для клиентов"),
        max_length=120, blank=True, default="",
        help_text=_("Если пусто — используется «Почта для клиентов»."),
    )
    contact_label_partners = models.CharField(
        verbose_name=_("Заголовок: почта для партнёров"),
        max_length=120, blank=True, default="",
        help_text=_("Если пусто — используется «Почта для партнёров»."),
    )
    contact_label_general = models.CharField(
        verbose_name=_("Заголовок: почта для общих вопросов"),
        max_length=120, blank=True, default="",
        help_text=_("Если пусто — используется «Почта для общих вопросов»."),
    )

    contact_email_clients = models.EmailField(_("Почта для клиентов"), blank=True, default="")
    contact_email_partners = models.EmailField(_("Почта для партнёров"), blank=True, default="")
    contact_email_general = models.EmailField(_("Почта для общих вопросов"), blank=True, default="")
    contact_telegram = models.CharField(_("Telegram для связи"), max_length=255, blank=True, default="", help_text=_("Ссылка t.me/... или @username"))

    social_vk = models.URLField("VK", blank=True, default="")
    social_tg = models.URLField("Telegram-канал", blank=True, default="")
    social_youtube = models.URLField("YouTube", blank=True, default="")
    social_dzen = models.URLField("Дзен", blank=True, default="")
    social_rutube = models.URLField("RuTube", blank=True, default="")
    social_instagram = models.URLField("Instagram", blank=True, default="")

    # --- [14] Партнёрская атрибуция (cookies) ---
    ref_attribution_window_days = models.PositiveIntegerField(
        verbose_name=_("Окно атрибуции (дней)"),
        default=90,
        help_text=_(
            "Срок жизни подписанной referral-cookie. "
            "Last click wins: последний клик по реферальной ссылке действует до регистрации. "
            "0 — не ставить долгоживущую cookie (только сессия до закрытия браузера)."
        ),
    )

    # === CSP (динамическая политика) ===
    csp_report_only = models.BooleanField(
        verbose_name=_("CSP: режим Report-Only"),
        default=False,
        help_text=_("Если включено — политика будет в режиме отчётов (не блокирует), заголовок 'Content-Security-Policy-Report-Only'."),
    )
    csp_extra_script_src = models.TextField(
        verbose_name=_("CSP: дополнительные источники script-src"),
        blank=True, default="",
        help_text=_(
            "Через запятую или пробел: например https://mc.yandex.ru https://code.jivo.ru https://www.googletagmanager.com 'unsafe-eval' (не рекомендуется)."),
    )
    csp_extra_style_src = models.TextField(
        verbose_name=_("CSP: дополнительные источники style-src"),
        blank=True, default="",
        help_text=_("Например: https://fonts.googleapis.com."),
    )
    csp_extra_img_src = models.TextField(
        verbose_name=_("CSP: дополнительные источники img-src"),
        blank=True, default="",
        help_text=_("Например: https://mc.yandex.ru data: blob:."),
    )
    csp_extra_connect_src = models.TextField(
        verbose_name=_("CSP: дополнительные источники connect-src"),
        blank=True, default="",
        help_text=_("Например: https://mc.yandex.ru https://api.example.com."),
    )
    csp_extra_frame_src = models.TextField(
        verbose_name=_("CSP: дополнительные источники frame-src"),
        blank=True, default="",
        help_text=_("Например: https://www.youtube.com https://player.vimeo.com."),
    )
    csp_extra_font_src = models.TextField(
        verbose_name=_("CSP: дополнительные источники font-src"),
        blank=True, default="",
        help_text=_("Например: https://fonts.gstatic.com data:."),
    )

    class Meta:
        verbose_name = _("Настройки сайта")
        verbose_name_plural = _("Настройки сайта")

    def __str__(self) -> str:
        return _gettext("Настройки сайта")

    @staticmethod
    def _normalize_domain(value: str) -> str:
        v = (value or "").strip().strip("/")
        if "://" in v:
            v = v.split("://", 1)[1]
        if "/" in v:
            v = v.split("/", 1)[0]
        return v.lower().rstrip(".")

    def clean(self):
        if self.admin_path in RESERVED_ADMIN_PREFIXES:
            raise ValidationError({"admin_path": _("Этот путь зарезервирован системой.")})

        # --- Валидация изображений OG/Twitter (минимум и пропорции) ---
        def check_card(file_field, label):
            f = getattr(self, file_field, None)
            if not f:
                return
            try:
                w, h = get_image_dimensions(f)
            except Exception:
                return
            # Минимальные размеры
            min_w, min_h = 600, 315
            if (w or 0) < min_w or (h or 0) < min_h:
                raise ValidationError({
                    file_field: _("%(label)s: минимальный размер — %(w)s×%(h)s пикселей.") % {
                        "label": label, "w": min_w, "h": min_h
                    }
                })
            # Пропорции ~1.91:1 (например, 1200×630) с допуском
            ratio = (w or 1) / float(h or 1)
            target, tol = 1.91, 0.15
            if not (target - tol) <= ratio <= (target + tol):
                raise ValidationError({
                    file_field: _("%(label)s: пропорции должны быть близки к 1.91:1 (например, 1200×630).") % {
                        "label": label
                    }
                })

        check_card("og_image", _("OG изображение"))
        check_card("twitter_image", _("Twitter изображение"))

    def save(self, *args, **kwargs):
        self.admin_path = (self.admin_path or "admin").strip().strip("/").lower() or "admin"
        self.domain = self._normalize_domain(self.domain or "swap.com")
        self.singleton = "main"

        self.full_clean()
        super().save(*args, **kwargs)

        # синхронизация django.contrib.sites
        site, _ = Site.objects.get_or_create(
            id=getattr(settings, "SITE_ID", 1),
            defaults={"domain": self.domain, "name": self.domain_view},
        )
        changed = False
        if site.domain != self.domain:
            site.domain = self.domain
            changed = True
        if site.name != self.domain_view:
            site.name = self.domain_view
            changed = True
        if changed:
            site.save(update_fields=["domain", "name"])

        # --- Инвалидация кэша get_site_setup() после сохранения ---
        try:
            from .services.site_setup import clear_site_setup_cache
            clear_site_setup_cache()
        except Exception:
            pass

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(
            singleton="main",
            defaults={
                "admin_path": "admin",
                "otp_issuer": "Swapers",
                "domain": "swap.com",
                "domain_view": "Swapers",
                "robots_txt": "User-agent: *\nDisallow:\n",
                "block_indexing": False,
            },
        )
        return obj
