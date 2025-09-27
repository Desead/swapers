# 2FA (TOTP) для админки

## Что это
Двухфакторная аутентификация включена **только для входа в админку**. Используется TOTP (Google Authenticator, 1Password, Authy и др.) на базе `django-otp` и плагина `otp_totp`.
**Без** `django-two-factor-auth`. - этот пакет использовать нельзя так как там постоянно возникает конфликт с типами передаваемых значений

- Middleware: `django_otp.middleware.OTPMiddleware`
- Админка: кастомный `RoleBasedOTPAdminSite` (см. `swapers/admin.py`), который требует:
  - `is_active` и `is_staff`
  - **подтверждённый OTP** (`request.user.is_verified()`)
  - членство в одной из разрешённых ролей (см. `docs/60-roles.md`)

## Как подключить 2FA (сотрудник)
1. Залогиниться на сайте (обычный вход).
2. Открыть **Безопасность (2FA)**: `/security/2fa/setup/`
3. Отсканировать QR в приложении-аутентификаторе.
4. Ввести 6-значный код → «Двухфакторная аутентификация включена».
5. Зайти в админку по вашему динамическому пути (смотри шапку сайта «Админка: /…/»).

> Если зайти в админку без подключённой 2FA, **редирект** отправит на `/security/2fa/setup/` (см. `Admin2FARedirectMiddleware`).

## Настройка “issuer”
Имя сервиса, отображаемое в приложении-аутентификаторе, берётся из `SiteSetup.otp_issuer`.
После изменения **нужен перезапуск** приложения, чтобы все процессы взяли новое значение. (Текущий процесс обновляется сигналом, но для консистентности — делайте рестарт.)

## Частые проблемы
- **QR не показывается** — убедитесь, что установлен пакет `qrcode[pil]`.
- **Код не принимается** — проверьте время на сервере (TOTP чувствителен к синхронизации).
- **В админку не пускает** — проверьте:
  - `is_staff=True` у пользователя,
  - есть ли нужная роль (см. `docs/60-roles.md`),
  - включена ли 2FA и введён ли код (статус `is_verified()`).

## Восстановление доступа (потеря устройства)
> Только для админов/поддержки через консоль.

Удалить TOTP-устройства пользователя (он подключит заново):
```py
python manage.py shell
>>> from django.contrib.auth import get_user_model
>>> from django_otp.plugins.otp_totp.models import TOTPDevice
>>> User = get_user_model()
>>> u = User.objects.get(email="staff@example.com")
>>> TOTPDevice.objects.filter(user=u).delete()
```

После этого сотрудник снова пройдёт на /security/2fa/setup/

## Точки интеграции в проекте

- Проверка 2FA + ролей в админке: swapers/admin.py
- Страница подключения и QR: app_main/views_2fa.py → /security/2fa/setup/
- Middleware редиректа в мастер 2FA: app_main/middleware.py (Admin2FARedirectMiddleware)
- Issuer из настроек сайта: SiteSetup.otp_issuer + сигнал обновления
