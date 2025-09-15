import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import translation
from django.conf import settings
from django.test import Client, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware


@pytest.fixture
def site_setup(db):
    # ВАЖНО: импортируем модель только здесь, когда Django уже сконфигурирован
    from app_main.models import SiteSetup
    s = SiteSetup.get_solo()
    s.domain = "example.com"
    s.domain_view = "Swap"
    s.admin_path = "admin"
    s.save()
    return s


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(email="u@example.com", password="pass123")


@pytest.fixture
def staff_user(db):
    User = get_user_model()
    return User.objects.create_user(
        email="staff@example.com", password="pass123", is_staff=True
    )


@pytest.fixture
def auth_client(client, user):
    assert client.login(email=user.email, password="pass123")
    return client


@pytest.fixture
def staff_client(client, staff_user):
    assert client.login(email=staff_user.email, password="pass123")
    return client


@pytest.fixture
def switch_lang(client, db):
    """Ставит язык в сессии + активирует его в текущем потоке (чтобы reverse() дал правильный префикс)."""

    def _switch(lang_code: str, next_url="/"):
        client.post(
            reverse("set_language"),
            {"language": lang_code, "next": next_url},
            follow=True,
        )
        # Активируем язык для текущего потока — reverse() начнёт отдавать /en/, /ru/, ...
        translation.activate(lang_code.split("-", 1)[0])
        return client

    return _switch


class Browser:
    """
    Упрощённый «браузер»:
    - .get/.post — ходят через Django test client (все middleware выполняются, куки сохраняются).
    - .make_request(path, method='get') — создаёт RequestFactory-запрос, НО с той же сессией/куками,
      что и у клиента (удобно для вызова сигналов, где нужен request-объект).
    """

    def __init__(self):
        self.client = Client()
        self.rf = RequestFactory()

    def get(self, path, **kwargs):
        return self.client.get(path, **kwargs)

    def post(self, path, data=None, **kwargs):
        return self.client.post(path, data or {}, **kwargs)

    def make_request(self, path="/", method="get"):
        method = method.lower()
        req = getattr(self.rf, method)(path)
        # перенесём все текущие куки клиента
        for k, morsel in self.client.cookies.items():
            req.COOKIES[k] = morsel.value

        # прокинем ту же сессию (как это делает SessionMiddleware)
        smw = SessionMiddleware(lambda r: None)
        smw.process_request(req)
        # если у клиента уже есть sessionid — SessionMiddleware её подхватит сам
        # если нет — создадим и вернём ключ обратно в клиент (чтобы последующие запросы имели ту же сессию)
        cookie_name = settings.SESSION_COOKIE_NAME
        if cookie_name not in req.COOKIES:
            req.session.save()
            self.client.cookies[cookie_name] = req.session.session_key
        return req

    def save_session_from_request(self, request):
        """Явно сохранить изменения сессии, сделанные на request (нужно, если не было ответа через SessionMiddleware)."""
        request.session.save()

    @property
    def session(self):
        return self.client.session

    def set_cookie(self, key, value):
        self.client.cookies[key] = value

    def get_cookie(self, key):
        c = self.client.cookies.get(key)
        return c.value if c else None


@pytest.fixture
def browser():
    return Browser()
