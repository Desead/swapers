from django.contrib.auth import get_user_model
from django.utils import timezone

from app_main.tests.base import FastTestCase
from app_main.tests.conftest import Browser  # используем наш удобный браузер
from app_main.middleware import REF_COOKIE_NAME
from app_main.models import SiteSetup
from allauth.account.signals import user_signed_up

User = get_user_model()


class ReferralCookieAndMetricsTests(FastTestCase):
    def setUp(self):
        self.browser = Browser()

        self.setup = SiteSetup.get_solo()
        self.setup.ref_attribution_window_days = 90
        self.setup.save()

        self.ref1 = User.objects.create_user(email="r1@ex.com", password="x")
        self.ref1.referral_code = "CODE1"
        self.ref1.save(update_fields=["referral_code"])

        self.ref2 = User.objects.create_user(email="r2@ex.com", password="x")
        self.ref2.referral_code = "CODE2"
        self.ref2.save(update_fields=["referral_code"])

    def test_last_click_wins_and_signup_delay_saved(self):
        # Первый визит: CODE1 -> Set-Cookie(ref_sig=...)
        resp1 = self.browser.get(f"/?ref={self.ref1.referral_code}")
        assert REF_COOKIE_NAME in resp1.cookies
        c1 = resp1.cookies[REF_COOKIE_NAME].value

        # Второй визит: CODE2 -> перезапишет cookie
        resp2 = self.browser.get(f"/?ref={self.ref2.referral_code}")
        assert REF_COOKIE_NAME in resp2.cookies
        c2 = resp2.cookies[REF_COOKIE_NAME].value
        assert c1 != c2, "last click должен перезаписать cookie"

        # Регистрация — тот же «браузер» (общие куки/сессия)
        req_signup = self.browser.make_request("/accounts/signup/")
        user = User.objects.create_user(email="u@ex.com", password="x")
        user.date_joined = timezone.now()
        user.save(update_fields=["date_joined"])

        user_signed_up.send(sender=user.__class__, request=req_signup, user=user)
        self.browser.save_session_from_request(req_signup)

        user.refresh_from_db()
        assert user.referred_by_id == self.ref2.id, "Должен победить последний клик"
        assert user.referral_first_seen_at is not None
        assert user.referral_signup_delay is not None
        assert user.referral_signup_delay.total_seconds() >= 0

        # Флаг удаления cookie выставлен
        assert req_signup.session.get("ref_cookie_delete") is True

    def test_window_zero_sets_session_only(self):
        # Отключаем persistent cookie
        self.setup.ref_attribution_window_days = 0
        self.setup.save()

        resp = self.browser.get(f"/?ref={self.ref1.referral_code}")
        # persistent-cookie не ставится
        assert REF_COOKIE_NAME not in resp.cookies

        # но в сессии «браузера» должен появиться referral_pending
        assert "referral_pending" in self.browser.session

        # Регистрация: request с той же сессией/куками
        req_signup = self.browser.make_request("/accounts/signup/")
        user = User.objects.create_user(email="sess@ex.com", password="x")
        user_signed_up.send(sender=user.__class__, request=req_signup, user=user)
        self.browser.save_session_from_request(req_signup)

        user.refresh_from_db()
        assert user.referred_by_id == self.ref1.id

    def test_cookie_deleted_after_signup(self):
        # Установим cookie визитом по реф-ссылке
        resp1 = self.browser.get(f"/?ref={self.ref1.referral_code}")
        assert REF_COOKIE_NAME in resp1.cookies

        # Регистрация -> выставит флаг удаления в сессии
        req_signup = self.browser.make_request("/accounts/signup/")
        user = User.objects.create_user(email="del@ex.com", password="x")
        user_signed_up.send(sender=user.__class__, request=req_signup, user=user)
        self.browser.save_session_from_request(req_signup)

        # Следующий реальный запрос через client должен отдать Set-Cookie удаления
        resp2 = self.browser.get("/")
        assert REF_COOKIE_NAME in resp2.cookies, "Ожидаем заголовок Set-Cookie для удаления ref-cookie"
        morsel = resp2.cookies[REF_COOKIE_NAME]
        assert (morsel["max-age"] == "0") or ("expires" in morsel and morsel["expires"]), "Cookie должна быть помечена как удалённая"

        # referral_pending/флаг удалены из сессии
        assert "referral_pending" not in self.browser.session
        assert not self.browser.session.get("ref_cookie_delete")
