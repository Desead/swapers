from decimal import Decimal

from django.test import RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from app_main.tests.base import FastTestCase

from allauth.account.models import EmailAddress
from allauth.account.signals import user_signed_up, email_confirmed


User = get_user_model()


def _request_with_session(path="/"):
    rf = RequestFactory()
    req = rf.get(path)
    # прикрутим сессию к RequestFactory-запросу
    SessionMiddleware(lambda r: None).process_request(req)
    req.session.save()
    return req


class ReferralAndBonusTests(FastTestCase):
    def setUp(self):
        self.referrer = User.objects.create_user(email="ref@ex.com", password="x", is_active=True)
        self.referrer.referral_code = "REFCODE123"
        self.referrer.save(update_fields=["referral_code"])

    def test_referrer_set_on_user_signed_up(self):
        """После сигнала user_signed_up user.referred_by должен заполниться, если в сессии есть ref_code."""
        req = _request_with_session()
        req.session["ref_code"] = self.referrer.referral_code

        new_user = User.objects.create_user(email="new@ex.com", password="x", is_active=True)
        # отправляем сигнал, как делает allauth в момент завершения регистрации
        user_signed_up.send(sender=new_user.__class__, request=req, user=new_user)

        new_user.refresh_from_db()
        self.assertEqual(new_user.referred_by_id, self.referrer.id)

    def test_bonus_awarded_after_first_email_confirmation(self):
        """Бонус начисляется только ПОСЛЕ первого подтверждения e-mail у приглашённого пользователя."""
        # сперва связываем приглашённого с реферером
        req = _request_with_session()
        req.session["ref_code"] = self.referrer.referral_code
        invited = User.objects.create_user(email="inv@ex.com", password="x", is_active=True)
        user_signed_up.send(sender=invited.__class__, request=req, user=invited)

        # проверка исходных значений у реферера
        self.referrer.refresh_from_db()
        self.assertEqual(self.referrer.count, 0)
        self.assertEqual(self.referrer.balance, Decimal("0"))

        # имитируем подтверждение первого e-mail
        ea1 = EmailAddress.objects.create(user=invited, email=invited.email, verified=True, primary=True)
        email_confirmed.send(sender=EmailAddress, request=req, email_address=ea1)

        self.referrer.refresh_from_db()
        self.assertEqual(self.referrer.count, 1)
        self.assertEqual(self.referrer.balance, Decimal("1.50"))

        # подтверждается ВТОРОЙ e-mail -> повторного начисления быть не должно
        ea2 = EmailAddress.objects.create(user=invited, email="alt@ex.com", verified=True, primary=False)
        email_confirmed.send(sender=EmailAddress, request=req, email_address=ea2)

        self.referrer.refresh_from_db()
        self.assertEqual(self.referrer.count, 1)
        self.assertEqual(self.referrer.balance, Decimal("1.50"))
