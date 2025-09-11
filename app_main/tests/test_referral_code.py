from django.contrib.auth import get_user_model
from app_main.tests.base import FastTestCase

User = get_user_model()

class ReferralCodeGenerationTests(FastTestCase):
    def test_referral_code_auto_generated_on_create(self):
        u = User.objects.create_user(email="a@ex.com", password="x")
        # сигнал post_save устанавливает код и делает второй save — обновим объект
        u.refresh_from_db()

        self.assertTrue(u.referral_code, "referral_code должен быть установлен")
        self.assertRegex(u.referral_code, r"^[A-Za-z0-9]+$", "Код должен быть буквенно-цифровым")
        # Не завязываемся жёстко на длину — допускаем разумный диапазон
        self.assertGreaterEqual(len(u.referral_code), 6)
        self.assertLessEqual(len(u.referral_code), 16)

    def test_referral_code_is_unique_across_many_users(self):
        emails = [f"user{i}@ex.com" for i in range(200)]
        codes = set()
        for e in emails:
            u = User.objects.create_user(email=e, password="x")
            u.refresh_from_db()
            self.assertTrue(u.referral_code, f"Код должен быть у {e}")
            self.assertNotIn(u.referral_code, codes, "Код должен быть уникальным")
            codes.add(u.referral_code)

    def test_referral_code_persists_on_update(self):
        u = User.objects.create_user(email="persist@ex.com", password="x", first_name="Old")
        u.refresh_from_db()
        code_before = u.referral_code
        # Меняем любые поля — код не должен меняться
        u.first_name = "New"
        u.save()
        u.refresh_from_db()
        self.assertEqual(u.referral_code, code_before, "Код не должен изменяться при апдейтах")
