from django.contrib.auth import get_user_model
from app_main.tests.base import FastTestCase

User = get_user_model()


class ReferralCodeGenerationTests(FastTestCase):
    def test_referral_code_auto_generated_on_create(self):
        u = User.objects.create_user(email="a@ex.com", password="x")
        u.refresh_from_db()

        assert u.referral_code, "referral_code должен быть установлен"
        assert u.referral_code.isalnum(), "Код должен быть буквенно-цифровым"
        assert 6 <= len(u.referral_code) <= 16

    def test_referral_code_is_unique_across_many_users(self):
        emails = [f"user{i}@ex.com" for i in range(200)]
        codes = set()
        for e in emails:
            u = User.objects.create_user(email=e, password="x")
            u.refresh_from_db()
            assert u.referral_code, f"Код должен быть у {e}"
            assert u.referral_code not in codes, "Код должен быть уникальным"
            codes.add(u.referral_code)

    def test_referral_code_persists_on_update(self):
        u = User.objects.create_user(email="persist@ex.com", password="x", first_name="Old")
        u.refresh_from_db()
        code_before = u.referral_code
        u.first_name = "New"
        u.save()
        u.refresh_from_db()
        assert u.referral_code == code_before, "Код не должен изменяться при апдейтах"
