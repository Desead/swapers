from django.core.management import call_command
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from app_main.tests.base import FastTestCase

from app_main.models import SiteSetup


User = get_user_model()


class InitRolesCommandTests(FastTestCase):
    @classmethod
    def setUpTestData(cls):
        # гарантируем, что контент-тайпы созданы (миграции уже прогнаны Django для тестовой БД)
        pass

    def test_init_roles_creates_groups_and_permissions(self):
        call_command("init_roles")

        # группы созданы
        for name in ["Admins", "Support", "Finance", "Content", "Admin-RO"]:
            self.assertTrue(Group.objects.filter(name=name).exists(), f"Group {name} must exist")

        # проверим выборочно право view_user у Support и export_users у Finance
        support = Group.objects.get(name="Support")
        finance = Group.objects.get(name="Finance")

        ct_user = ContentType.objects.get_for_model(User)
        p_view_user = Permission.objects.get(codename="view_user", content_type=ct_user)
        p_export = Permission.objects.get(codename="export_users", content_type=ct_user)

        self.assertIn(p_view_user, support.permissions.all())
        self.assertIn(p_export, finance.permissions.all())

        # Admins должен иметь change_sitesetup
        ct_site = ContentType.objects.get_for_model(SiteSetup)
        p_change_site = Permission.objects.get(codename="change_sitesetup", content_type=ct_site)
        admins = Group.objects.get(name="Admins")
        self.assertIn(p_change_site, admins.permissions.all())
