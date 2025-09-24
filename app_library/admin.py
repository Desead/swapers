from django.contrib import admin
from django.utils.safestring import mark_safe

from app_library.models import BannerAsset
from django.utils.translation import gettext_lazy as _t
from .models_templates import DocumentTemplate

@admin.register(BannerAsset)
class BannerAssetAdmin(admin.ModelAdmin):
    list_display = ("name", "theme", "size_kb", "preview")
    search_fields = ("name",)
    readonly_fields = ("preview", "size_kb")
    ordering = ("name",)
    fieldsets = (
        (None, {
            "fields": ("name", "theme", "file", "preview", "size_kb")
        }),
    )

    def size_kb(self, obj):
        if obj.size_bytes:
            return f"{obj.size_bytes / 1024:.1f} KB"
        return "—"

    size_kb.short_description = _t("Размер")

    def preview(self, obj):
        try:
            if obj.file and obj.file.url:
                url = obj.file.url
                # SVG тоже показываем через <img>
                return mark_safe(
                    f'<img src="{url}" alt="" style="max-width:176px; max-height:62px; height:auto; width:auto; border:1px solid #ddd; border-radius:4px;">'
                )
        except Exception:
            pass
        return "—"

    preview.short_description = _t("Превью")

@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    save_on_top = True
    list_display = ("kind_label", "title", "updated_at")
    # list_display_links = ("title",)
    fields = ("kind", "title", "body", "updated_at")
    readonly_fields = ("updated_at",)

    @admin.display(description=_t("Тип"))
    def kind_label(self, obj: DocumentTemplate):
        return obj.get_kind_display()
