from decimal import Decimal

from django.test import RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.utils import timezone

from app_main.tests.base import FastTestCase
from app_main.middleware import ReferralAttributionMiddleware, REF_COOKIE_NAME
from app_main.models import SiteSetup

from allauth.account.models import EmailAddress
from allauth.account.signals import user_signed_up, email_confirmed

User = get_user_model()


def _request_with_session(path="/"):
    rf = RequestFactory()
    req = rf.get(path)
    SessionMiddleware(lambda r: None).process_request(req)
    req.session.save()
    return req


class ReferralAndBonusTests(FastTestCase):
    def setUp(self):
        # Настройки: окно атрибуции > 0, чтобы ставилась подписанная cookie
        setup = SiteSetup.get_solo()
        setup.ref_attribution_window_days = 90
        setup.save()

        self.referrer = User.objects.create_user(email="ref@ex.com", password="x", is_active=True)
        self.referrer.referral_code = "REFCODE123"
        self.referrer.save(update_fields=["referral_code"])

    def test_referrer_set_on_user_signed_up_via_cookie(self):
        """После user_signed_up user.referred_by должен заполниться (через подписанную cookie)."""
        # Первый визит по реф-ссылке
        req1 = _request_with_session(path=f"/?ref={self.referrer.referral_code}")
        mw = ReferralAttributionMiddleware(lambda r: HttpResponse("OK"))
        resp1 = mw(req1)
        # Подписанная cookie должна появиться
        assert REF_COOKIE_NAME in resp1.cookies

        # Регистрация (allauth шлёт сигнал с request, который несёт cookie)
        # Смоделируем новый запрос (как будто другая страница регистрации)
        req_signup = _request_with_session(path="/accounts/signup/")
        req_signup.COOKIES[REF_COOKIE_NAME] = resp1.cookies[REF_COOKIE_NAME].value

        new_user = User.objects.create_user(email="new@ex.com", password="x", is_active=True)
        user_signed_up.send(sender=new_user.__class__, request=req_signup, user=new_user)

        new_user.refresh_from_db()
        assert new_user.referred_by_id == self.referrer.id

    def test_bonus_awarded_after_first_email_confirmation(self):
        """Бонус начисляется только ПОСЛЕ первого подтверждения e-mail у приглашённого пользователя."""
        # Связываем приглашённого через cookie
        req1 = _request_with_session(path=f"/?ref={self.referrer.referral_code}")
        mw = ReferralAttributionMiddleware(lambda r: HttpResponse("OK"))
        resp1 = mw(req1)

        invited = User.objects.create_user(email="inv@ex.com", password="x", is_active=True)

        req_signup = _request_with_session(path="/accounts/signup/")
        req_signup.COOKIES[REF_COOKIE_NAME] = resp1.cookies[REF_COOKIE_NAME].value
        user_signed_up.send(sender=invited.__class__, request=req_signup, user=invited)

        # Проверка исходных значений у реферера
        self.referrer.refresh_from_db()
        assert self.referrer.count == 0
        assert self.referrer.balance == Decimal("0")

        # Имитация подтверждения ПЕРВОГО e-mail
        ea1 = EmailAddress.objects.create(user=invited, email=invited.email, verified=True, primary=True)
        email_confirmed.send(sender=EmailAddress, request=req_signup, email_address=ea1)

        self.referrer.refresh_from_db()
        assert self.referrer.count == 1
        assert self.referrer.balance == Decimal("1.50")

        # Подтверждается ВТОРОЙ e-mail -> повторного начисления быть не должно
        ea2 = EmailAddress.objects.create(user=invited, email="alt@ex.com", verified=True, primary=False)
        email_confirmed.send(sender=EmailAddress, request=req_signup, email_address=ea2)

        self.referrer.refresh_from_db()
        assert self.referrer.count == 1
        assert self.referrer.balance == Decimal("1.50")
