import pytest

from app_main.services.site_setup import get_site_setup, clear_site_setup_cache, get_admin_prefix
from app_main.models import SiteSetup


@pytest.mark.django_db
def test_cache_invalidation_on_save():
    clear_site_setup_cache()
    s1 = get_site_setup()
    assert isinstance(s1, SiteSetup)

    # меняем поле и сохраняем → кэш должен сброситься
    new_issuer = "Swapers QA"
    s1.otp_issuer = new_issuer
    s1.save()

    s2 = get_site_setup()
    assert s2.otp_issuer == new_issuer  # новые данные подхвачены сразу


@pytest.mark.django_db
def test_cache_invalidation_on_delete():
    clear_site_setup_cache()
    s1 = get_site_setup()
    pk1 = s1.pk

    # удаляем singleton → сигнал post_delete сбрасывает кэш
    s1.delete()

    # новый вызов вернёт свежесозданный объект (get_or_create в get_solo)
    s2 = get_site_setup()
    assert s2.pk != pk1
    assert isinstance(s2, SiteSetup)


@pytest.mark.django_db
def test_get_admin_prefix_reads_fresh_values():
    clear_site_setup_cache()
    s = get_site_setup()
    s.admin_path = "super-admin"
    s.save()

    # без ручного cache_clear — должен видеть новое значение
    assert get_admin_prefix() == "super-admin"
