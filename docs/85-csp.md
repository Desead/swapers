# CSP в проекте Swapers

Этот документ описывает, **как у нас включён Content Security Policy (CSP)**, что он защищает, где настроен, и как его
безопасно изменять.

---

## Зачем CSP

CSP — это заголовок, которым мы говорим браузеру **откуда можно грузить/исполнять ресурсы**. Он сильно снижает риск XSS
и «утечек» через внешние запросы.

Ключевые эффекты:

- Запрет неразрешённого JS/CSS (включая инлайны без nonce).
- Контроль источников картинок/шрифтов и сетевых запросов.
- Запрет встраивания сайта в чужие iframe.
- **Report-Only** режим для диагностики перед включением строгого режима.

---

## Как сделано у нас

### Библиотека

- Используем **`django-csp`** + **fallback-мидлварь** (страховка на случай, если кто-то вернёт ответ слишком рано и
  стандартный m/w не выставит заголовок).

### Заголовок и порядок middleware

В активном `settings`:

```python
MIDDLEWARE = [
    "csp.middleware.CSPMiddleware",  # ← CSP ставим ПЕРВЫМ
    "app_main.middleware_csp_fallback.CSPHeaderEnsureMiddleware",  # ← страховка
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "app_main.middleware.ReferralMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "app_main.middleware.Admin2FARedirectMiddleware",
]
```

Fallback-мидлварь ничего не делает, если django-csp уже проставил заголовок. Если нет — соберёт политику из CSP_* и
добавит заголовок сам.

# Для своих инлайнов (если появятся) используйте nonce:

```html

<script nonce="{{ request.csp_nonce }}">
    // ваш инлайновый JS
</script>

<style nonce="{{ request.csp_nonce }}">
    /* ваш инлайновый CSS */
</style>
```

- Внешним файлам nonce не нужен — они разрешаются через SCRIPT_SRC/STYLE_SRC
- Атрибутные обработчики (onclick="...") строгая CSP всё равно блокирует — их лучше не использовать.

# Как включать/усиливать CSP

1. Сейчас: режим Report-Only (CSP_REPORT_ONLY=True) — ничего не блокируется, но отчёты шлются на /csp-report/.
   Проверь логи, убедись, что нет неожиданных нарушений.

2. Включить блокировку: Когда отчёты чистые, поменяйте:

```python
CSP_REPORT_ONLY = False
```

- Перезапустите сервис.

3. Ужесточение для отдельных страниц:

- Для ваших вьюх, где добавлены nonce и нет «грязных» инлайнов, можно точечно убрать 'unsafe-inline':

```python
from csp.decorators import csp_replace


@csp_replace(SCRIPT_SRC=("'self'",), STYLE_SRC=("'self'",))
def my_view(request):
    ...
```

- Админку при этом оставляем мягкой (с 'unsafe-inline'), иначе придётся переопределять её шаблоны.

# Что можно менять/добавлять

- CDN/домены: добавляйте в соответствующие директивы:
  CSP_SCRIPT_SRC, CSP_STYLE_SRC, CSP_FONT_SRC, CSP_IMG_SRC, CSP_CONNECT_SRC.
  Пример:

```python
CSP_SCRIPT_SRC += ("https://unpkg.com",)
CSP_STYLE_SRC += ("https://cdn.jsdelivr.net",)
CSP_FONT_SRC += ("https://fonts.gstatic.com",)
```

- Report-Only ↔ Enforce: меняйте CSP_REPORT_ONLY.
- Nonce: используйте в своих шаблонах на инлайнах — это позволит убрать 'unsafe-inline' точечно.
- Fallback-мидлварь: можно убрать, когда будете уверены, что django-csp всегда проставляет заголовок в вашем стеке (
  тогда просто удалите строку из MIDDLEWARE).

# На что обратить внимание

- Порядок middleware: csp.middleware.CSPMiddleware стоит первым; fallback — сразу за ним.
- Окружения: если dev/prod переопределяют MIDDLEWARE, не забудьте в них продублировать строки для CSP.
- Кэш: не кэшируйте HTML-ответы, в которых уже «впаян» конкретный nonce (он одноразовый). Статические страницы без
  инлайнов — ок.
- Админка: оставляем 'unsafe-inline' глобально, либо используем отдельную политику для админки. Переопределять шаблоны
  админки ради nonce обычно нецелесообразно.

# Быстрая проверка вручную

```terminaloutput
- главная
curl.exe -sI http://127.0.0.1:8000/ | findstr /I "Content-Security-Policy"

- логин админки (если кастомный префикс — подставить)
curl.exe -sI http://127.0.0.1:8000/admin/login/ | findstr /I "Content-Security-Policy"
```

# Проблемы

- Нет заголовка CSP:
  Проверь, что csp.middleware.CSPMiddleware стоит первым, а fallback подключён вторым. Убедись, что изменяли активный
  модуль настроек.

- CDN блокируется:
  Добавь его домен в нужную директиву CSP_*.

- Инлайны блокируются:
  Либо пометь их nonce, либо вынеси в файл и подключи через src/href.

- Нет отчётов:
  Включите логгер на /csp-report/ и провоцируйте нарушение (например, <img src="https://example.com/x.png"> при
  img-src 'self' data:).

# Что дальше
- Когда «Report-Only» чист, переведите на Enforce.
- На публичных страницах постепенно уходите от 'unsafe-inline' к nonce и точечным политикам через @csp_replace.
- Оставляйте fallback-мидлварь как страховку; удалить можно в любой момент, когда убедитесь, что без него заголовок всегда есть.

