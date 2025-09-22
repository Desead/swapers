from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.core.validators import FileExtensionValidator

MAX_BANNER_MB = 1
_MAX_BYTES = MAX_BANNER_MB * 1024 * 1024


def validate_banner_filesize(f):
    if not f:
        return
    try:
        size = f.size  # InMemoryUploadedFile / TemporaryUploadedFile
    except Exception:
        return
    if size > _MAX_BYTES:
        raise ValidationError(
            _("Максимальный размер файла — %(mb)d МБ. Сейчас: %(size).1f МБ."),
            params={"mb": MAX_BANNER_MB, "size": size / (1024 * 1024)},
        )


# --- библиотека баннеров ---
class BannerAsset(models.Model):
    class Theme(models.TextChoices):
        DARK = "dark", _("Тёмный")
        LIGHT = "light", _("Светлый")

    name = models.CharField(_("Название"), max_length=120)
    theme = models.CharField(_("Тема"), max_length=5, choices=Theme.choices, default=Theme.DARK)
    # FileField, чтобы поддержать SVG; валидируем расширение и размер
    file = models.FileField(
        _("Файл баннера"),
        upload_to="partners/banners/",
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "gif", "svg"]),
            validate_banner_filesize,
        ],
    )
    # служебное
    size_bytes = models.PositiveIntegerField(_("Размер файла (байт)"), blank=True, null=True, editable=False)
    created_at = models.DateTimeField(_("Создан"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Обновлён"), auto_now=True)

    class Meta:
        verbose_name = _("Баннер")
        verbose_name_plural = _("Библиотека баннеров")
        ordering = ("name",)

    def __str__(self):
        return f"{self.name} ({self.get_theme_display()})"

    def save(self, *args, **kwargs):
        try:
            f = self.file
            if f and hasattr(f, "size"):
                self.size_bytes = f.size
        except Exception:
            pass
        super().save(*args, **kwargs)
