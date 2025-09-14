from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

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
