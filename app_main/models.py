from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.utils import timezone
from django.core.validators import validate_email, RegexValidator
from django.core.exceptions import ValidationError
from django.conf import settings
from django.contrib.sites.models import Site
from django.utils.translation import gettext_lazy as _  # lazy — для verbose_name/help_text
from django.utils.translation import gettext as _gettext  # runtime — для __str__ и сообщений


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


class SiteSetup(models.Model):
    """Singleton with site settings."""
    singleton = models.CharField(max_length=16, unique=True, default="main", editable=False)

    # домен и отображаемое имя сайта
    domain = models.CharField(
        verbose_name=_("Домен (без http/https)"),
        max_length=253,
        default="swap.com",
        help_text=_("Например: example.com или localhost (без http/https)."),
        validators=[
            RegexValidator(
                # допускаем localhost ИЛИ обычные домены вида sub.example.com
                regex=r"^(localhost|(?:(?!-)[A-Za-z0-9-]{1,63}(?<!-)\.)+[A-Za-z]{2,63})$",
                message=_("Введите корректное доменное имя, например: example.com"),
            )
        ],
    )
    domain_view = models.CharField(
        verbose_name=_("Отображаемое имя сайта"),
        max_length=100,
        default="Swap",
        help_text=_('Название для заголовков/письма и т.п., например: "Swap".'),
    )

    admin_path = models.CharField(
        verbose_name=_("Путь к админке"),
        max_length=50,
        default="admin",
        validators=[
            RegexValidator(
                regex=r"^[a-z0-9-]+$",
                message=_("Разрешены только маленькие латинские буквы, цифры и дефис"),
            )
        ],
        help_text=_("Например: supera-dmin"),
    )
    otp_issuer = models.CharField(
        verbose_name=_("Название сервиса для 2FA"),
        max_length=64,
        default="Swapers",
        validators=[
            RegexValidator(
                regex=r"^[A-Za-z0-9 ._-]+$",
                message=_("Допустимы латиница, цифры, пробел, точка, дефис, подчёркивание."),
            )
        ],
        help_text=_('Отобразится в приложении-аутентификаторе (например: "Swapers").'),
    )

    class Meta:
        verbose_name = _("Настройки сайта")
        verbose_name_plural = _("Настройки сайта")

    def __str__(self) -> str:
        return _gettext("Настройки сайта")  # runtime-строка, не lazy

    @staticmethod
    def _normalize_domain(value: str) -> str:
        """Strip scheme/path and lowercase."""
        v = (value or "").strip().strip("/")
        if "://" in v:
            v = v.split("://", 1)[1]
        if "/" in v:
            v = v.split("/", 1)[0]
        return v.lower().rstrip(".")

    def clean(self):
        if self.admin_path in RESERVED_ADMIN_PREFIXES:
            raise ValidationError({"admin_path": _("Этот путь зарезервирован системой.")})

    def save(self, *args, **kwargs):
        # Нормализация → валидация → сохранение
        self.admin_path = (self.admin_path or "admin").strip().strip("/").lower() or "admin"
        self.domain = self._normalize_domain(self.domain or "swap.com")
        self.singleton = "main"

        self.full_clean()
        super().save(*args, **kwargs)

        # Синхронизируем django.contrib.sites по SITE_ID
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

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(
            singleton="main",
            defaults={
                "admin_path": "admin",
                "otp_issuer": "Swapers",
                "domain": "swap.com",
                "domain_view": "Swap",
            },
        )
        return obj
