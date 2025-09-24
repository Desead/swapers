from django.db import models
from django_ckeditor_5.fields import CKEditor5Field
from django.utils.translation import gettext_lazy as _t
from django.contrib import admin
from .enums import DocumentTemplateType


class DocumentTemplate(models.Model):
    """
    Единая библиотека RU-шаблонов документов.
    Переводы тут не нужны: клиент создаёт Document из шаблона и переводит уже сам.
    """
    kind = models.CharField(_t("Тип"), max_length=32, choices=DocumentTemplateType.CHOICES, unique=True)
    title = models.CharField(_t("Заголовок (RU)"), max_length=200)
    body = CKEditor5Field(_t("Текст (RU)"), config_name="default", blank=True, default="")
    updated_at = models.DateTimeField(_t("Обновлён"), auto_now=True)

    class Meta:
        verbose_name = _t("Шаблон документа")
        verbose_name_plural = _t("Шаблоны документов")
        ordering = ("kind",)

    def __str__(self):
        return f"{self.get_kind_display()} — {self.title}"

    @admin.display(description=_t("Тип"))
    def get_kind_display(self):
        # удобная подпись для админки (list_display)
        return dict(DocumentTemplateType.CHOICES).get(self.kind, self.kind)
