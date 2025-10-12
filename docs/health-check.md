Вот полностью обновлённая и дополняемая документация. Её можно сохранить как `docs/health-check.md` (или заменить существующий файл в репозитории).

---

# Health-check провайдеров ликвидности и связанные фичи

> Эта версия обновляет и расширяет прежнюю инструкцию: добавлены новые типы провайдеров (EXCHANGER, WALLET, NODE, BANK), партнёрские ссылки, группировка провайдеров в админке, Bybit и дополнительные эндпоинты статуса/времени. 

## TL;DR

* Поле `Exchange.is_available` выставляется **автоматически** (health-check).
* Режимы `can_receive` / `can_send` независимы, но **работают только если** `is_available=True`.
* Для `CASH` и пока для `PSP`/`WALLET`/`NODE`/`BANK` — `is_available=True` (проверки будут позже).
* Для CEX/DEX: сначала **status/maintenance** (если есть), затем **time/ping**.
* Команда: `python manage.py market_healthcheck [опции]`.
* Партнёрская ссылка для каждого провайдера берётся **из кода** и отображается в админке как кликабельный линк.

---

## Термины и модели

### Exchange (поставщик ликвидности)

Ключевые поля:

* `provider` — провайдер из фиксированного enum `LiquidityProvider` (метки **без i18n**).
* `exchange_kind` — тип:
  `CEX`, `DEX`, `PSP`, `WALLET`, `NODE`, `EXCHANGER`, `BANK`, `CASH`.
* `is_available` — автоматически выставляемый флаг доступности.
* `can_receive`, `can_send` — ручные режимы работы.
* Комиссии (торговые и на ввод/вывод), `stablecoin`, `show_prices_on_home`, `webhook_endpoint`.
* `partner_url` (read-only свойство) — ссылка на сайт/партнёрку провайдера из словаря в коде.

### Правила доступности

1. `is_available` — **только авто-проверка**.
2. Фактическая способность работать:

   * `can_receive_effective = is_available AND can_receive`
   * `can_send_effective = is_available AND can_send`
3. `CASH` — `is_available=True` всегда.
4. Пока `PSP`, `WALLET`, `NODE`, `BANK` — `is_available=True` (заглушка на будущее).
5. CEX/DEX — см. «Механика проверки» ниже.

---

## Где лежит код

* Сервис: `app_market/services/health.py`

  * `check_exchange(exchange, persist=True) -> HealthResult` — главная точка.
  * `effective_modes(exchange) -> dict` — расчёт фактических режимов.
  * `_CEX_STATUS_PROBES` и `_CEX_TIME_PROBES` — словари эндпоинтов.
* Команда: `app_market/management/commands/market_healthcheck.py`.
* Партнёрские ссылки: словарь `PROVIDER_PARTNER_LINKS` рядом с `LiquidityProvider` в `app_market/models/exchange.py` + свойство `Exchange.partner_url`.
* Группировка провайдеров в админке: метод `formfield_for_choice_field` в `ExchangeAdmin` (только UI).

---

## Механика проверки (CEX/DEX)

Алгоритм для каждой записи `Exchange`:

1. Если есть **status**-эндпойнт — запросить его:

* Если «maintenance/closed» → `is_available=False` (`code=MAINTENANCE`), на этом всё.
* Если статус непонятен/недоступен → не роняем, идём к пункту 2.

2. Запросить **time/ping**:

* `HTTP 200` → `True` (`OK`)
* `401/403` → `False` (`AUTH_ERROR`)
* `429` → `False` (`RATE_LIMIT`)
* `5xx`/таймаут/URLError → `False` (`NETWORK_DOWN`)
* прочее → `False` (`UNKNOWN`)

3. Нет ни status, ни time/ping: `SKIPPED_NO_PROBE` и **сейчас** считаем `available=True` (консервативно).

### Остальные типы

* `CASH` — `True` (по политике).
* `PSP`, `WALLET`, `NODE`, `BANK` — пока `True`; место под будущие проверки зарезервировано в `check_exchange()`.

---

## Готовые эндпоинты

**STATUS (maintenance):**

* WhiteBIT → `https://whitebit.com/api/v4/public/platform/status`
* Bybit → `https://api.bybit.com/v5/system/status`
* Binance → `https://api.binance.com/sapi/v1/system/status`
* OKX → `https://www.okx.com/api/v5/system/status`
* HTX (Huobi) → `https://api.huobi.pro/v2/market-status`
* Bitfinex → `https://api-pub.bitfinex.com/v2/platform/status`

**TIME/PING (server time / лёгкий GET):**

* KuCoin → `https://api.kucoin.com/api/v1/timestamp`
* WhiteBIT → `https://whitebit.com/api/v4/public/time`
* MEXC → `https://api.mexc.com/api/v3/time`
* Bybit → `https://api.bybit.com/v5/market/time`
* Rapira → `https://api.rapira.net/open/system/time`
* Binance → `https://api.binance.com/api/v3/time`
* Coinbase Exchange → `https://api.exchange.coinbase.com/time`
* Upbit → `https://api.upbit.com/v1/market/all`
* Bitstamp → `https://www.bitstamp.net/api/v2/ticker/btcusd/`
* BingX → `https://open-api.bingx.com/openApi/spot/v1/common/time`
* Bitfinex → `https://api-pub.bitfinex.com/v2/ticker/tBTCUSD`
* HTX (Huobi) → `https://api.huobi.pro/v1/common/timestamp`
* Gate.io → `https://api.gateio.ws/api/v4/spot/time`
* Bitget → `https://api.bitget.com/api/v2/public/time`
* OKX → `https://www.okx.com/api/v5/public/time`
* Gemini → `https://api.gemini.com/v1/pricefeed`
* LBank → `https://api.lbkex.com/v2/timestamp.do`

> Если у провайдера есть только «time/ping» — этого достаточно. Если нет ни одного безопасного публичного эндпоинта — провайдер попадёт в `SKIPPED_NO_PROBE`.

---

## Как добавить нового провайдера

1. **Enum:** добавить в `LiquidityProvider` (метки без i18n).
2. **Запись в БД:** создать `Exchange(provider=<PROVIDER>)` (админка/сид/скрипт).
3. **Эндпоинты:** при необходимости пополнить словари в `app_market/services/health.py`:

```python
_CEX_STATUS_PROBES.update({
    LiquidityProvider.<PROVIDER>: "https://.../status",
})
_CEX_TIME_PROBES.update({
    LiquidityProvider.<PROVIDER>: "https://.../time_or_ping",
})
```

4. (Опционально) Маппинг вида в `_auto_kind_from_provider()` (если нужен авто-тип).
5. (Опционально) Добавить партнёрскую ссылку в `PROVIDER_PARTNER_LINKS`.

---

## Команда `market_healthcheck`

**Запуск:**

```bash
python manage.py market_healthcheck [--provider P] [--kind K] [--only-home] [--dry-run] [--verbose]
```

**Аргументы:**

* `--provider P` — фильтр по провайдерам (можно несколько) из `LiquidityProvider`
  (например: `KUCOIN`, `BYBIT`, `RAPIRA`, `BINANCE`, `OKX` и т.д.)
* `--kind K` — фильтр по типам: `CEX`, `DEX`, `PSP`, `WALLET`, `NODE`, `EXCHANGER`, `BANK`, `CASH`.
* `--only-home` — проверять только с `show_prices_on_home=True`.
* `--dry-run` — не сохранять `is_available`, только печатать результат.
* `--verbose` — подробный вывод (код, задержка, эффективные режимы, путь проверки).

**Примеры:**

```bash
# Все провайдеры подробно
python manage.py market_healthcheck --verbose

# KuCoin + Bybit, без сохранения
python manage.py market_healthcheck --provider KUCOIN --provider BYBIT --dry-run --verbose

# Только те, что на главной
python manage.py market_healthcheck --only-home --verbose
```

**Типовой вывод `--verbose`:**

```
KuCoin       | kind=CEX     | is_avail=True (OK)            | recv=True send=True  | 42ms | via=status/time
WhiteBIT     | kind=CEX     | is_avail=False (MAINTENANCE)  | recv=False send=False| 35ms | via=status/time
Rapira       | kind=CEX     | is_avail=True (OK)            | recv=True send=True  | 27ms | via=time
PayPal       | kind=PSP     | is_avail=True (SKIPPED_PSP)   | recv=True send=True  | 0ms  | via=SKIPPED_PSP
CASH       | kind=CASH  | is_avail=True (SKIPPED_MANUAL)| recv=False send=True | 0ms  | via=SKIPPED_MANUAL
```

---

## Партнёрские ссылки

* Словарь `PROVIDER_PARTNER_LINKS` в `app_market/models/exchange.py`.
* Свойство `Exchange.partner_url` возвращает URL (по умолчанию — официальный сайт).
* В админке поле `partner_link` (read-only) рендерится как кликабельный `<a>`
  с текстом «Перейти на сайт {Название}».
* Для `CASH` ссылка пустая («—» в админке).
* Позже можно заменить на UTM/реферальные линк-билдеры.

---

## Группировка провайдеров в админке

В `ExchangeAdmin` переопределён `formfield_for_choice_field` для поля `provider`,
чтобы `<select>` показывал **optgroup**:

* Ручной режим
* Централизованные биржи (CEX)
* Децентрализованные (DEX)
* Обменники (EXCHANGER)
* Кошельки (WALLET)
* Ноды (NODE)
* Платёжные системы (PSP)
* Банки (BANK)

Группировка — это **только UI**. На модель и health-check не влияет.

---

## Расписание (до Celery)

* Каждые **60–120 сек** — общий прогон (`market_healthcheck`).
* Каждые **30–60 сек** — «главные» поставщики (`--only-home`).
* На Windows — Task Scheduler, позже на Ubuntu переведём на Celery beat.

---

## Безопасность и логи

* В логи пишем только коды и краткие детали (без секретов/ключей).
* Эндпоинты — только публичные GET (без авторизации).
* Для `PSP`/`WALLET`/`NODE`/`BANK` проверки будут добавляться позже (отдельные политики).

---

## Частые вопросы

**Почему провайдера нет в выводе команды?**
— Нет записи в БД (`Exchange(provider=...)`) или вы отфильтровали его `--provider/--only-home`.

**Можно ли оставить только `status` без `time`?**
— Не рекомендуется: бывают случаи, когда статус-страница работает, а API лежит (и наоборот).

**Что, если у провайдера нет публичных эндпоинтов?**
— Оставляем как `SKIPPED_NO_PROBE` (сейчас — `available=True`). По желанию поведение можно сменить на «не менять текущее значение».

---

## План развития

* Добавить проверки для `PSP`/`WALLET`/`NODE`/`BANK` (oauth/ping RPC/chain head/мерчанты).
* Перевести планировщик на Celery beat, добавить backoff и счётчик флапов.
* Вынести коды и последние результаты в read-only панель админки.

---
