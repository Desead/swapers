from django.contrib import admin
from django.utils.safestring import mark_safe

from app_library.models import BannerAsset
from django.utils.translation import gettext_lazy as _


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

    size_kb.short_description = _("Размер")

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

    preview.short_description = _("Превью")
