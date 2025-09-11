from django.test import TestCase, override_settings

FAST_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

@override_settings(
    PASSWORD_HASHERS=FAST_HASHERS,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class FastTestCase(TestCase):
    """Базовый класс: быстрые пароли и почта в памяти только для тестов."""
    pass
