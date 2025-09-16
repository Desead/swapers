import pytest
from django.contrib import admin as djadmin
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.db import models as djmodels

from app_main.admin import SiteSetupAdmin
from app_main.models import SiteSetup


def test_user_admin_is_registered_in_admin_site():
    """Гарантируем, что кастомная модель пользователя зарегистрирована в админке."""
    User = get_user_model()
    assert User in djadmin.site._registry, "Custom User model is NOT registered in admin site"


@pytest.mark.django_db
def test_sitesetupadmin_urlfield_assume_scheme_https():
    """
    Проверяем, что formfield_overrides в SiteSetupAdmin действительно применились:
    все URLField в форме имеют assume_scheme='https'.
    """
    rf = RequestFactory()
    request = rf.get("/admin/app_main/sitesetup/1/change/")

    ma = SiteSetupAdmin(SiteSetup, djadmin.site)
    Form = ma.get_form(request)
    form = Form()

    # Соберём имена всех URLField из модели
    url_field_names = [
        f.name for f in SiteSetup._meta.get_fields()
        if isinstance(f, djmodels.URLField)
    ]
    assert url_field_names, "SiteSetup should have URLFields to test"

    # Не все поля могут быть в форме (например, readonly/file), поэтому проверяем те, что есть
    checked = 0
    for name in url_field_names:
        if name in form.base_fields:
            field = form.base_fields[name]
            assert getattr(field, "assume_scheme", None) == "https", f"{name}: assume_scheme must be 'https'"
            checked += 1

    assert checked > 0, "No URLField from model ended up in the form; check admin form configuration"
