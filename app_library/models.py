import re
from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _t
from django.core.validators import FileExtensionValidator
from django.core.files.base import ContentFile

MAX_BANNER_MB = 1
_MAX_BYTES = MAX_BANNER_MB * 1024 * 1024

def validate_banner_filesize(f):
    if not f:
        return
    try:
        size = f.size
    except Exception:
        return
    if size > _MAX_BYTES:
        raise ValidationError(
            _t("Максимальный размер файла — %(mb)d МБ. Сейчас: %(size).1f МБ."),
            params={"mb": MAX_BANNER_MB, "size": size / (1024 * 1024)},
        )

# --- минимальный санитайзер SVG ---
_SVG_TAG_RE = re.compile(rb"<svg[\s>]", re.I)
_XML_DECL_RE = re.compile(rb"<\?xml[^>]*\?>", re.I)
_DOCTYPE_RE = re.compile(rb"<!DOCTYPE[^>]*>", re.I)
_SCRIPT_TAG_RE = re.compile(rb"<\s*script[^>]*>.*?<\s*/\s*script\s*>", re.I | re.S)
_FOREIGNOBJECT_RE = re.compile(rb"<\s*foreignObject[^>]*>.*?<\s*/\s*foreignObject\s*>", re.I | re.S)
_EVENT_ATTR_RE = re.compile(rb"\s+on[a-zA-Z]+\s*=\s*(['\"]).*?\1", re.I | re.S)
_DANGEROUS_HREF_RE = re.compile(
    rb"\s+(?:xlink:)?href\s*=\s*(['\"])\s*(?:javascript:|data:)[^'\"]*\1", re.I
)
_DANGEROUS_STYLE_RE = re.compile(
    rb"\s+style\s*=\s*(['\"]).*?(?:url\s*\(|expression\s*\(|-moz-binding\s*:).*?\1",
    re.I | re.S,
)

def _sanitize_svg_bytes(data: bytes) -> bytes:
    # Ничего не делаем, если это не похоже на SVG
    if not _SVG_TAG_RE.search(data):
        return data
    # Убираем декларации / doctype
    data = _XML_DECL_RE.sub(b"", data)
    data = _DOCTYPE_RE.sub(b"", data)
    # Режем опасные узлы и атрибуты
    data = _SCRIPT_TAG_RE.sub(b"", data)
    data = _FOREIGNOBJECT_RE.sub(b"", data)
    data = _EVENT_ATTR_RE.sub(b"", data)
    data = _DANGEROUS_HREF_RE.sub(b"", data)
    data = _DANGEROUS_STYLE_RE.sub(b"", data)
    return data
# --- /санитайзер SVG ---

class BannerAsset(models.Model):
    class Theme(models.TextChoices):
        DARK = "dark", _t("Тёмный")
        LIGHT = "light", _t("Светлый")

    name = models.CharField(_t("Название"), max_length=120)
    theme = models.CharField(_t("Тема"), max_length=5, choices=Theme.choices, default=Theme.DARK)
    file = models.FileField(
        _t("Файл баннера"),
        upload_to="partners/banners/",
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "gif", "svg"]),
            validate_banner_filesize,
        ],
    )
    size_bytes = models.PositiveIntegerField(_t("Размер файла (байт)"), blank=True, null=True, editable=False)
    created_at = models.DateTimeField(_t("Создан"), auto_now_add=True)
    updated_at = models.DateTimeField(_t("Обновлён"), auto_now=True)

    class Meta:
        verbose_name = _t("Баннер")
        verbose_name_plural = _t("Библиотека баннеров")
        ordering = ("name",)

    def __str__(self):
        return f"{self.name} ({self.get_theme_display()})"

    def save(self, *args, **kwargs):
        f = self.file
        if f:
            # санитизируем только .svg
            name_lower = (getattr(f, "name", "") or "").lower()
            try:
                f.open("rb")
            except Exception:
                pass
            try:
                raw = f.read() or b""
            except Exception:
                raw = b""

            if name_lower.endswith(".svg") and raw:
                cleaned = _sanitize_svg_bytes(raw)
                if cleaned != raw:
                    # Перезаписываем содержимое тем же именем, не вызывая повторный save модели
                    self.file.save(f.name, ContentFile(cleaned), save=False)
                    self.size_bytes = len(cleaned)
                else:
                    # без изменений — просто обновим размер
                    self.size_bytes = len(raw)
            else:
                # не svg — сохраняем размер как есть
                try:
                    self.size_bytes = f.size
                except Exception:
                    self.size_bytes = None

        super().save(*args, **kwargs)

from .models_templates import DocumentTemplate