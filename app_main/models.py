from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser, PermissionsMixin, BaseUserManager
)
from django.utils import timezone
from django.core.validators import validate_email
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email обязателен")
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
            raise ValueError("Суперпользователь должен иметь is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Суперпользователь должен иметь is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    # аутентификация
    email = models.EmailField("Email", unique=True, db_index=True)
    first_name = models.CharField("Имя", max_length=150, blank=True)
    last_name = models.CharField("Фамилия", max_length=150, blank=True)
    phone = models.CharField("Телефон", max_length=32, blank=True)
    company = models.CharField("Компания", max_length=255, blank=True)

    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    # партнёрка
    referred_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="referrals", verbose_name="Кто привёл"
    )
    referral_code = models.CharField("Партнёрский код", max_length=16, unique=True, blank=True)
    count = models.PositiveIntegerField("Партнёров привлечено", default=0)
    balance = models.DecimalField("Партнёрский баланс, $", max_digits=12, decimal_places=2, default=0)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
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

    admin_path = models.CharField("Путь к админке", max_length=50, default="admin",
                                  validators=[RegexValidator(regex=r"^[a-z0-9-]+$", message="Разрешены только маленькие латинские буквы,цифры и дефис", )],
                                  help_text="Например: supera-dmin", )
    otp_issuer = models.CharField("Название сервиса для 2FA", max_length=64, default="Swapers", validators=[
        RegexValidator(regex=r"^[A-Za-z0-9 ._-]+$", message="Допустимы латиница, цифры, пробел, точка, дефис, подчёркивание.", )],
                                  help_text='Отобразится в приложении-аутентификаторе (например: "Swapers").', )

    class Meta:
        verbose_name = "Настройки сайта"
        verbose_name_plural = "Настройки сайта"

    def __str__(self) -> str:
        return "Настройки сайта"

    def clean(self):
        # Бизнес-валидация: запрет некоторых префиксов.
        if self.admin_path in RESERVED_ADMIN_PREFIXES:
            raise ValidationError({"admin_path": "Этот путь зарезервирован системой."})

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
