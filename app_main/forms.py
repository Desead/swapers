from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from .models import SiteSetup
from django.core.files.images import get_image_dimensions
from django.core.exceptions import ValidationError

User = get_user_model()


class AccountForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "company"]
        labels = {
            "first_name": _("Имя"),
            "last_name": _("Фамилия"),
            "phone": _("Телефон"),
            "company": _("Компания"),
        }
        # Если используешь плейсхолдеры — тоже пометь:
        widgets = {
            "first_name": forms.TextInput(attrs={"placeholder": _("Имя")}),
            "last_name": forms.TextInput(attrs={"placeholder": _("Фамилия")}),
            "phone": forms.TextInput(attrs={"placeholder": _("Телефон")}),
            "company": forms.TextInput(attrs={"placeholder": _("Компания")}),
        }

class SiteSetupAdminForm(forms.ModelForm):
    class Meta:
        model = SiteSetup
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()

        def check_card(img_field, label):
            file = cleaned.get(img_field)
            if not file:
                return
            try:
                width, height = get_image_dimensions(file)
            except Exception:
                return
            # Минимальные размеры (best practice для OG/Twitter)
            min_w, min_h = 600, 315
            if width < min_w or height < min_h:
                raise ValidationError({
                    img_field: _("%(label)s: минимальный размер — %(w)s×%(h)s пикселей.") % {
                        "label": label, "w": min_w, "h": min_h
                    }
                })
            # Пропорции ~1.91:1 (например, 1200×630). Допускаем небольшое отклонение.
            ratio = width / float(height or 1)
            target, tol = 1.91, 0.15
            if not (target - tol) <= ratio <= (target + tol):
                raise ValidationError({
                    img_field: _("%(label)s: пропорции должны быть близки к 1.91:1 (например, 1200×630).") % {
                        "label": label
                    }
                })

        check_card("og_image", _("OG изображение"))
        check_card("twitter_image", _("Twitter изображение"))

        return cleaned