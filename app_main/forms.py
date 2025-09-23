from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _t

User = get_user_model()


class AccountForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "company"]
        labels = {
            "first_name": _t("Имя"),
            "last_name": _t("Фамилия"),
            "phone": _t("Телефон"),
            "company": _t("Компания"),
        }
        widgets = {
            "first_name": forms.TextInput(attrs={"placeholder": _t("Имя")}),
            "last_name": forms.TextInput(attrs={"placeholder": _t("Фамилия")}),
            "phone": forms.TextInput(attrs={"placeholder": _t("Телефон")}),
            "company": forms.TextInput(attrs={"placeholder": _t("Компания")}),
        }
