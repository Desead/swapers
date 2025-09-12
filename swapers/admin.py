from django.contrib.admin.apps import AdminConfig

class OTPAdminConfig(AdminConfig):
    # ВАЖНО: строкой указываем класс из swapers.role_admin
    default_site = "swapers.role_admin.RoleBasedOTPAdminSite"

    def ready(self):
        super().ready()
        from django.contrib import admin
