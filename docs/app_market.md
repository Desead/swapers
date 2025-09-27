# Документация: биржи и API-ключи (app_market)

Эта страница описывает реализованный функционал моделей **Exchange** и **ExchangeApiKey**, шифрование секретов, маскирование для админки, настройки и тесты. Стек: **Python 3.13.7**, **Django 5.2.6**, Windows 11.

---

## 1) Модель `Exchange` — карточка биржи

**Файл:** `app_market/models/exchange.py`
**Назначение:** хранит базовые параметры биржи и флаги поведения.

### Поля

* `name: CharField(unique=True)` — **уникальное** название биржи (например, `Binance`, `OKX`).
* `is_available: BooleanField(editable=False, default=True, db_index=True)` — авто-флаг доступности биржи (меняется сервисом health-check; **не редактируется вручную**, но виден в админке).
* `can_receive: BooleanField(default=True)` — биржа принимает средства.
* `can_send: BooleanField(default=True)` — биржа отдает средства.
* `stablecoin: CharField(default="USDT")` — рабочий стейблкоин для расчётов; **не пустой**. В `save()` нормализуется в UPPERCASE и триммится.
* Комиссии (**могут быть отрицательными**, по умолчанию `0.1`):

  * `spot_taker_fee: DecimalField`
  * `spot_maker_fee: DecimalField`
  * `futures_taker_fee: DecimalField`
  * `futures_maker_fee: DecimalField`
* `show_prices_on_home: BooleanField(default=False, db_index=True)` — «цены на главную».

Все пользовательские строки помечены для i18n через `_t`.

---

## 2) Модель `ExchangeApiKey` — шифрование и маски

**Файл:** `app_market/models/account.py`
**Назначение:** хранит **зашифрованные** ключи и их маски для безопасного отображения.

### Связи и уникальность

* `exchange: ForeignKey(Exchange, related_name="api_keys")`
* `label: CharField` — метка набора ключей (например, `main`, `trading`, `withdraw`).
* **Ограничение уникальности:** пара (`exchange`, `label`) уникальна — один именованный набор ключей на одну биржу.

### Секреты (зашифрованные поля)

* `api_key: EncryptedCharField(null=True, blank=True)`
* `api_secret: EncryptedCharField(null=True, blank=True)`
* `api_passphrase: EncryptedCharField(null=True, blank=True)`

> Используется пакет `django-encrypted-model-fields` + `cryptography`. Данные в БД хранятся в виде шифртекста.

### Маски-дублёры (только для просмотра)

* `api_key_view: CharField(editable=False)`
* `api_secret_view: CharField(editable=False)`
* `api_passphrase_view: CharField(editable=False)`

**Логика маскирования** (выполняется в `save()` автоматически):

* `len >= 6`: первые 3 символа + `**********` + последние 3 (например, `abc**********def`)
* `3 <= len < 6`: первые 3 символа + `**********`
* `0 < len < 3`: **показываем только** `**********` (не раскрываем короткие значения)
* пусто/None → пусто

Таким образом, сотрудники в админке видят **только маску**, а не исходное значение.

---

## 3) Админка

**Файл:** `app_market/admin/exchanges_admin.py` (у тебя может называться иначе; важно, что в `admin/__init__.py` этот модуль импортируется).

### `ExchangeAdmin`

* `readonly_fields = ("is_available",)` — статус биржи **только для чтения**.
* Выведены флаги режимов и комиссии.
* Фильтры и поиск по имени/стейблкоину.

### `ExchangeApiKeyAdmin`

* Ввод секретов (`api_key`, `api_secret`, `api_passphrase`) через `PasswordInput` — **текущее значение не показывается**.
* В списке и на форме **отображаются** только поля-маски `*_view` (**readonly**).
* Структура формы разделена на блоки: «Отображение (маски)» и «Секреты (ввод/обновление)».

### Импорт админ-подмодулей

Если админка разнесена по файлам, убедись, что в `app_market/admin/__init__.py` ты импортируешь подмодули, чтобы сработали декораторы регистрации:

```python
# простой вариант
from .exchanges_admin import *  # noqa: F401,F403
# + импорт других модулей при их появлении
```

или через `importlib`:

```python
from importlib import import_module
for m in ("exchanges_admin",):
    import_module(f"{__name__}.{m}")
```

---

## 4) Настройки шифрования

В `settings.py` уже добавлен ключ из файла (рекомендуемый подход без .env):

```python
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
SECRETS_DIR = BASE_DIR / ".secrets"
SECRETS_DIR.mkdir(exist_ok=True)
FIELD_KEY_FILE = SECRETS_DIR / "field_encryption.key"

def _read_or_create_field_key(path: Path) -> str:
    from cryptography.fernet import Fernet
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    key = Fernet.generate_key().decode("utf-8")
    path.write_text(key, encoding="utf-8")
    return key

FIELD_ENCRYPTION_KEY = _read_or_create_field_key(FIELD_KEY_FILE)
```

**Важно:**

* Добавь `.secrets/` в `.gitignore`.
* При деплое перенеси файл `field_encryption.key` на сервер (иначе старые записи не расшифруются).
* Бэкап ключа обязателен.

---

## 5) Миграции и установка

```powershell
pip install django-encrypted-model-fields cryptography
python manage.py makemigrations app_market
python manage.py migrate
```

---

## 6) Тесты

**Папка:** `app_market/tests/`

Покрыто:

* Exchange: дефолты, нормализация `stablecoin`, уникальность `name`.
* ExchangeApiKey: маскирование (`*_view`) для разных длин/None/пустых, обновление маски при изменении ключа, уникальность (`exchange`, `label`) с корректной обработкой `IntegrityError` в `transaction.atomic()`.
* Админка: `readonly_fields`, `PasswordInput` для секретов, вывод `*_view` в `list_display`.

Запуск:

```powershell
pytest -q
# или целевой набор
pytest -q app_market/tests
```

---

## 7) Потоки данных и безопасность

* **Хранение:** секреты всегда в шифре (БД/дампы не раскрывают ключи).
* **Отображение:** в админке показываются **только маски**.
* **Редактирование:** чтобы сменить ключ, админ вводит новое значение; старое не отображается вовсе.
* **Доступ:** ограничь доступ к модели `ExchangeApiKey` ролями/пермишенами; логируй изменения (опц. через `django-simple-history`/аудит).
* **Бэкапы:** храни копию `field_encryption.key` отдельно от БД.
* **Ротация ключа шифрования:** базово потребует re-encrypt (скрипт, который для каждой записи читает значение, переключает `FIELD_ENCRYPTION_KEY`, и сохраняет заново). План ротации можно добавить позже.

---

## 8) Типовые сценарии

### Добавление биржи

1. В админке создаёшь `Exchange` — задаёшь `name`, при необходимости — комиссии, флаги режимов, `stablecoin`.
2. Поле `is_available` видишь, но не редактируешь (его заполнит health-check сервис).

### Добавление ключей

1. В админке открываешь `ExchangeApiKey` (или создаёшь новый).
2. Вводишь `label` и при необходимости секреты (`api_key`, `api_secret`, `api_passphrase`).
3. После сохранения увидишь маски `*_view` — **без раскрытия** исходной строки.

### Проверка уникальности

* В рамках одной биржи **нельзя** создать два набора ключей с одинаковой меткой `label`.
* Ту же `label` можно использовать на другой бирже.

---

## 9) План на доработку (по желанию)

* **Health-check** бирж: management-команда или Celery beat, которая пингует публичные эндпоинты/ccxt и автоматически проставляет `is_available`.
* **Admin action**: «Проверить доступность сейчас».
* **Аудит/история**: логирование изменений секретов (только факт/время/автор, без значения).
* **Права**: разнести права на чтение/изменение `Exchange` и `ExchangeApiKey` для разных ролей.
* **Ротация шифрования**: утилита «re-encrypt» при смене `FIELD_ENCRYPTION_KEY`.

---
