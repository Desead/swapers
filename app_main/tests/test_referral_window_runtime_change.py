import pytest

from django.contrib.auth import get_user_model

from app_main.services.site_setup import get_site_setup, clear_site_setup_cache
from app_main.middleware import REF_COOKIE_NAME

User = get_user_model()


@pytest.mark.django_db
def test_referral_cookie_respects_runtime_change(client):
    clear_site_setup_cache()

    # Реферал с кодом
    ref = User.objects.create_user(email="ref@ex.com", password="x")
    assert ref.referral_code

    # 1) Долгое окно атрибуции → persistent cookie ставится
    setup = get_site_setup()
    setup.ref_attribution_window_days = 90
    setup.save()

    resp1 = client.get(f"/?ref={ref.referral_code}")
    assert REF_COOKIE_NAME in resp1.cookies

    # 2) Меняем на 0 → persistent cookie НЕ ставится (только сессионная логика)
    setup = get_site_setup()
    setup.ref_attribution_window_days = 0
    setup.save()

    resp2 = client.get(f"/?ref={ref.referral_code}")
    assert REF_COOKIE_NAME not in resp2.cookies
