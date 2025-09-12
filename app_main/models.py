from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser, PermissionsMixin, BaseUserManager
)
from django.utils import timezone
from django.core.validators import validate_email
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django.conf import settings

# ленивые строки — для verbose_name, help_text, labels и т.п.
from django.utils.translation import gettext_lazy as _
# обычный gettext — чтобы вернуть уже готовую str в __str__
from django.utils.translation import gettext as _gettext


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

    # НОВОЕ: предпочитаемый язык пользователя
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
        # Индексы под аналитику рефералок
        indexes = [
            models.Index(fields=["referred_by", "date_joined"], name="user_ref_by_date_idx"),
            models.Index(fields=["date_joined"], name="user_joined_idx"),
        ]
        # Кастомные права для ролей
        permissions = [
            ("export_users", "Can export users"),
            ("view_finance", "Can view finance dashboards"),
        ]

    def __str__(self):
        return self.email


RESERVED_ADMIN_PREFIXES = {"static", "media", "api", "accounts", }


class SiteSetup(models.Model):
    """
    Синглтон с настройками сайта.
    """
    # сторож для единственности
    singleton = models.CharField(max_length=16, unique=True, default="main", editable=False)

    admin_path = models.CharField(
        verbose_name=_("Путь к админке"),
        max_length=50,
        default="admin",
        validators=[
            RegexValidator(
                regex=r"^[a-z0-9-]+$",
                message=_("Разрешены только маленькие латинские буквы,цифры и дефис"),
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
        # Возвращаем уже вычисленную строку, не lazy-объект
        return _gettext("Настройки сайта")

    def clean(self):
        # Бизнес-валидация: запрет некоторых префиксов.
        if self.admin_path in RESERVED_ADMIN_PREFIXES:
            raise ValidationError({"admin_path": _("Этот путь зарезервирован системой.")})

    def save(self, *args, **kwargs):
        # Нормализация ПЕРЕД full_clean(): так валидатор проверит уже нормализованное значение
        value = (self.admin_path or "admin").strip().strip("/").lower()
        self.admin_path = value or "admin"
        self.singleton = "main"
        # Запускаем валидаторы полей + clean() + validate_unique()
        self.full_clean()
        return super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(
            singleton="main",
            defaults={"admin_path": "admin", "otp_issuer": "Swapers"},
        )
        return obj
