# Тесты (overview + как запускать быстро)

Цель набора автотестов — покрыть ключевые бизнес-потоки проекта минимальным, но полезным набором:

- Регистрация по реферальной ссылке и начисление бонуса **после** подтверждения e-mail.
- Доступ в админку: 2FA + роли (Groups) + суперпользователь.
- Инициализация ролей и прав командой `init_roles`.
- Генерация реферальных кодов: автоматическая, уникальная и неизменная при апдейтах.

## Где лежат тесты

app_main/tests/

- base.py # базовый FastTestCase (ускорители для тестов)
- test_admin_access_roles_2fa.py
- test_init_roles_command.py
- test_referral_and_bonus.py
- test_referral_code.py

## Как запускать

Базовый запуск:

```py
python manage.py test
```

# Почему тесты бегают быстро

В app_main/tests/base.py определён FastTestCase, который:

- включает быстрый хэшер пароля (MD5PasswordHasher);
- переключает почту на in-memory бэкенд (locmem).
- Все тестовые классы наследуются от FastTestCase, поэтому создание пользователей и отправка писем не тормозят выполнение.

# Что именно проверяем

1) Реферал + бонус (после подтверждения e-mail)

- Файл: test_referral_and_bonus.py
- test_referrer_set_on_user_signed_up — при регистрации с ?ref=<code> поле referred_by у нового пользователя заполняется
сигналом user_signed_up.
- test_bonus_awarded_after_first_email_confirmation — бонус (+1.50 и count += 1) начисляется только при первом
подтверждении e-mail (сигнал email_confirmed). Повторные подтверждения не удваивают бонус.
- В обработчике используется свежее чтение referred_by_id из БД, чтобы не попасть на устаревший экземпляр пользователя.

2) Доступ в админку: 2FA + роли

- Файл: test_admin_access_roles_2fa.py
- Проверяем логику нашего RoleBasedOTPAdminSite.has_permission:
- is_staff=False → отказ.
- is_staff=True, но нет 2FA (is_verified=False) → отказ.
- is_staff=True + 2FA, но нет роли → отказ.
- is_staff=True + 2FA + роль (например, Support) → доступ.
- Суперпользователь (is_superuser=True) + 2FA → доступ.
- Замечание: OTP эмулируется подстановкой метода user.is_verified(); реальные устройства не создаём (это юнит-тест).

3) Команда init_roles

- Файл: test_init_roles_command.py
- Команда создаёт группы Admins, Support, Finance, Content, Admin-RO.
- Назначаются базовые модельные права и наши кастомные (export_users, view_finance).
- Группе Admins выдано change_sitesetup.

4) Генерация реферального кода

- Файл: test_referral_code.py
- test_referral_code_auto_generated_on_create — при создании пользователя код ставится автоматически, буквенно-цифровой,
разумной длины.
- test_referral_code_is_unique_across_many_users — массовое создание пользователей даёт уникальные коды.
- test_referral_code_persists_on_update — код не меняется при обновлении полей пользователя.

# Частые проблемы и их решения

- ImportError: 'tests' module incorrectly imported… — в корне не должно быть tests.py; папка app_main/tests должна
содержать __init__.py.
- AppRegistryNotReady / RuntimeWarning о БД в ready() — мы убрали любые запросы к БД из AppConfig.ready(); инициализация
SiteSetup и применение issuer делаются в post_migrate и на страницах, где это необходимо.
- Падает тест на бонус — убедитесь, что обработчик email_confirmed читает referred_by_id из БД по user_id, а не из
email_address.user.

# Рекомендации по написанию новых тестов

- Наследуйтесь от FastTestCase, чтобы не тормозить прогон.
- Для представлений используйте RequestFactory и прикручивайте сессии через SessionMiddleware.
- Для прав и ролей используйте perms или выдавайте роль через Group.objects.get(name=...).
- Интеграцию с реальным TOTP можно протестировать отдельно (создание TOTPDevice, подтверждение кода), но юниты должны
оставаться быстрыми.
