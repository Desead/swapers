import json
import re
import pytest
from django.conf import settings
from django.utils import translation
from django.test import Client, RequestFactory
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.urls import reverse
from django.test.utils import override_settings
from django.contrib.auth.hashers import reset_hashers

from app_main.models import SiteSetup

# --- авто-создание singleton SiteSetup для всех тестов ---
@pytest.fixture(autouse=True)
def _ensure_singleton(db):
    SiteSetup.get_solo()

# --- удобный доступ к SiteSetup ---
@pytest.fixture
def site_setup(db):
    return SiteSetup.get_solo()

# --- парсер JSON-LD из разметки ---
@pytest.fixture
def extract_jsonld():
    script_re = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(?P<json>.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    def _extract(html: str):
        m = script_re.search(html)
        return json.loads(m.group("json")) if m else None
    return _extract

# --- переключение языка, совместимо с вызовами switch_lang('ru', next_url='/') ---
@pytest.fixture
def switch_lang(client, settings):
    def _set(lang_code="ru", next_url="/", **_ignore):
        translation.activate(lang_code)
        client.defaults["HTTP_ACCEPT_LANGUAGE"] = lang_code
        s = client.session
        s["_language"] = lang_code
        s.save()
        client.cookies["django_language"] = lang_code
        return lang_code
    return _set

# --- staff-клиент без username (у нас email — логин) ---
@pytest.fixture
def staff_client(db, client, django_user_model):
    user = django_user_model.objects.create_user(
        email="staff@example.com",
        password="pass1234",
        is_staff=True,
        is_superuser=False,
    )
    client.force_login(user)
    return client

# --- вспомогалка: достаём «ru»-код, реально присутствующий в проекте ---
def _preferred_ru_code():
    langs = [code.lower() for code, _ in getattr(settings, "LANGUAGES", [])]
    for cand in ("ru", "ru-ru"):
        if cand in langs:
            return cand
    # если ни одного «ru*» нет — берём первый из LANGUAGES или 'ru'
    return langs[0] if langs else "ru"

# --- HTML главной: форсируем язык и пробуем кандидаты путей, чтобы исключить 404 ---
@pytest.fixture
def get_home_html(client):
    def _get():
        lang_code = _preferred_ru_code()
        translation.activate(lang_code)
        client.defaults["HTTP_ACCEPT_LANGUAGE"] = lang_code
        client.cookies["django_language"] = lang_code
        s = client.session
        s["_language"] = lang_code
        s.save()

        # пробуем несколько вариантов (reverse + i18n-prefix’ы)
        candidates = [reverse("home")]
        if "/" not in candidates:
            candidates.append("/")
        for prefix in {lang_code, "ru", "ru-ru"}:
            candidates.append(f"/{prefix.strip('/')}/")

        last_resp = None
        for path in candidates:
            resp = client.get(path, follow=True)
            last_resp = resp
            if resp.status_code == 200:
                return resp.content.decode("utf-8")

        # если вдруг ничего не сработало — явно падаем с информацией
        raise AssertionError(
            f"Home not reachable. Tried: {', '.join(candidates)}; "
            f"last_status={getattr(last_resp, 'status_code', None)}"
        )
    return _get

# --- Back-compat helper для старых тестов (рефералы/метрики) ---
class Browser:
    """
    Обёртка над django.test.Client с минимально нужной совместимостью
    для старых тестов: перенос куки/сессии в "сырой" Request и обратно.
    """
    def __init__(self):
        self._client = Client()
        self._extra = {}  # headers для ближайшего запроса
        self._rf = RequestFactory()

    @property
    def client(self) -> Client:
        return self._client

    def set_header(self, key: str, value: str):
        if not key.upper().startswith("HTTP_") and key.lower() not in ("content_type", "content_length"):
            key = f"HTTP_{key.replace('-', '_').upper()}"
        self._extra[key] = value
        return self

    def get(self, path: str, data=None, **kwargs):
        extra = {**self._extra}
        self._extra.clear()
        return self._client.get(path, data=data or {}, **extra, **kwargs)

    def post(self, path: str, data=None, content_type=None, **kwargs):
        extra = {**self._extra}
        self._extra.clear()
        return self._client.post(path, data=data or {}, content_type=content_type, **extra, **kwargs)

    @property
    def cookies(self):
        return self._client.cookies

    @property
    def session(self):
        return self._client.session

    def make_request(self, path: str, method: str = "get", data=None):
        """
        Сырой Request с прикрученной СЕССИЕЙ текущего client + его КУКАМИ.
        Нужен для сигналов allauth в реферальных тестах.
        """
        method = method.lower()
        req = getattr(self._rf, method)(path, data=data or {})
        SessionMiddleware(lambda r: None).process_request(req)
        for k, v in self._client.session.items():
            req.session[k] = v
        req.COOKIES = {**{k: v.value for k, v in self._client.cookies.items()}, **req.COOKIES}
        req.user = AnonymousUser()
        return req

    def save_session_from_request(self, request):
        """
        Переносим изменения request.session обратно в client.session.
        """
        cs = self._client.session
        for k in list(cs.keys()):
            if k not in request.session:
                del cs[k]
        for k, v in request.session.items():
            cs[k] = v
        cs.save()


@pytest.fixture(autouse=True, scope="session")
def fast_password_hashers_session():
    # быстрый хешер на всю сессию тестов
    with override_settings(PASSWORD_HASHERS=[
        "django.contrib.auth.hashers.MD5PasswordHasher",
    ]):
        try:
            reset_hashers(setting="PASSWORD_HASHERS")
        except TypeError:
            reset_hashers()
        yield
        try:
            reset_hashers(setting="PASSWORD_HASHERS")
        except TypeError:
            reset_hashers()