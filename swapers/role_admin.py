from django_otp.admin import OTPAdminSite  # импорт безопасен здесь — этот модуль загрузят ПОСЛЕ старта приложений

# Разрешённые группы (кроме суперпользователя)
ALLOWED_ADMIN_GROUPS = {"Admins", "Support", "Finance", "Content", "Admin-RO"}


class RoleBasedOTPAdminSite(OTPAdminSite):
    """
    Админка с обязательным OTP на форме логина (реализует django-otp)
    + допуск только по ролям. Суперпользователь проходит ПОСЛЕ OTP.
    """
    def has_permission(self, request):
        # Требует is_active, is_staff и ПОДТВЕРЖДЁННУЮ 2FA
        if not super().has_permission(request):
            return False

        user = request.user
        if user.is_superuser:
            return True

        return user.groups.filter(name__in=ALLOWED_ADMIN_GROUPS).exists()
