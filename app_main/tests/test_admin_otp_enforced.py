# app_main/tests/test_admin_otp_enforced.py
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory

from app_main.tests.base import FastTestCase  # быстрые хэшеры/почта
from swapers.role_admin import RoleBasedOTPAdminSite  # наш класс AdminSite с OTP

User = get_user_model()


def _req_with_user(user):
    rf = RequestFactory()
    req = rf.get("/")
    SessionMiddleware(lambda r: None).process_request(req)
    req.session.save()
    req.user = user
    return req


def _set_verified(user, value: bool):
    # эмулируем поведение OTPMiddleware: добавляем метод is_verified()
    user.is_verified = (lambda v=value: (lambda: v))()


class AdminOTPEnforcementTests(FastTestCase):
    def setUp(self):
        # гарантируем наличие групп (ролей), чтобы проверка ролей была валидной
        for name in ["Admins", "Support", "Finance", "Content", "Admin-RO"]:
            Group.objects.get_or_create(name=name)

    def test_admin_site_is_role_based_otp(self):
        """В проекте реально активен наш OTP-админсайт (а не дефолтный AdminSite)."""
        self.assertIsInstance(admin.site, RoleBasedOTPAdminSite)

    def test_staff_with_role_but_without_otp_is_denied(self):
        """Staff + роль, но без 2FA → доступа нет."""
        u = User.objects.create_user(email="staff@ex.com", password="x", is_active=True, is_staff=True)
        u.groups.add(Group.objects.get(name="Support"))
        _set_verified(u, False)

        req = _req_with_user(u)
        self.assertFalse(admin.site.has_permission(req))

    def test_staff_with_role_and_otp_is_allowed(self):
        """Staff + роль + 2FA → доступ есть."""
        u = User.objects.create_user(email="allow@ex.com", password="x", is_active=True, is_staff=True)
        u.groups.add(Group.objects.get(name="Support"))
        _set_verified(u, True)

        req = _req_with_user(u)
        self.assertTrue(admin.site.has_permission(req))

    def test_superuser_requires_otp(self):
        """Суперпользователь без 2FA — отказ; с 2FA — доступ."""
        su = User.objects.create_user(
            email="root@ex.com", password="x", is_active=True, is_staff=True, is_superuser=True
        )

        _set_verified(su, False)
        self.assertFalse(admin.site.has_permission(_req_with_user(su)))

        _set_verified(su, True)
        self.assertTrue(admin.site.has_permission(_req_with_user(su)))
