# app_main/tests/test_admin_access_roles_2fa.py
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.sessions.middleware import SessionMiddleware

from app_main.tests.base import FastTestCase  # быстрые хэшеры/почта
from swapers.role_admin import RoleBasedOTPAdminSite  # <-- правильный импорт

User = get_user_model()


def rf_request_with_user(user):
    rf = RequestFactory()
    req = rf.get("/")
    SessionMiddleware(lambda r: None).process_request(req)
    req.session.save()
    req.user = user
    return req


def _set_verified(user, value: bool):
    # эмулируем поведение OTPMiddleware: добавляем метод is_verified()
    user.is_verified = (lambda v=value: (lambda: v))()


class AdminAccessRole2FATests(FastTestCase):
    def setUp(self):
        self.site = RoleBasedOTPAdminSite()
        # группы, одна из которых даст доступ
        for name in ["Admins", "Support", "Finance", "Content", "Admin-RO"]:
            Group.objects.get_or_create(name=name)

        self.staff = User.objects.create_user(email="staff@ex.com", password="x", is_active=True, is_staff=True)
        self.super = User.objects.create_user(email="root@ex.com", password="x", is_active=True, is_staff=True, is_superuser=True)
        self.nostaff = User.objects.create_user(email="user@ex.com", password="x", is_active=True, is_staff=False)

    def test_non_staff_denied(self):
        _set_verified(self.nostaff, True)
        req = rf_request_with_user(self.nostaff)
        self.assertFalse(self.site.has_permission(req))

    def test_staff_without_2fa_denied(self):
        _set_verified(self.staff, False)
        req = rf_request_with_user(self.staff)
        self.assertFalse(self.site.has_permission(req))

    def test_staff_with_2fa_but_no_role_denied(self):
        _set_verified(self.staff, True)
        req = rf_request_with_user(self.staff)
        self.assertFalse(self.site.has_permission(req))

    def test_staff_with_2fa_and_role_allowed(self):
        _set_verified(self.staff, True)
        g = Group.objects.get(name="Support")
        self.staff.groups.add(g)
        req = rf_request_with_user(self.staff)
        self.assertTrue(self.site.has_permission(req))

    def test_superuser_with_2fa_allowed(self):
        _set_verified(self.super, True)
        req = rf_request_with_user(self.super)
        self.assertTrue(self.site.has_permission(req))
