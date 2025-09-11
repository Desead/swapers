from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()


class AccountForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "company"]
        labels = {
            "first_name": "Имя",
            "last_name": "Фамилия",
            "phone": "Телефон",
            "company": "Компания",
        }
