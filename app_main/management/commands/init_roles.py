# app_main/management/commands/init_roles.py
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from app_main.models import SiteSetup

User = get_user_model()

ROLE_NAMES = ["Admins", "Support", "Finance", "Content", "Admin-RO"]

class Command(BaseCommand):
    help = "Создаёт/обновляет группы ролей и назначает права (idempotent)."

    def handle(self, *args, **options):
        # Контент-тайпы наших моделей
        ct_user = ContentType.objects.get_for_model(User)
        ct_site = ContentType.objects.get_for_model(SiteSetup)

        # Базовые perms
        p = {}
        def get_perm(codename, ct):
            return Permission.objects.get(codename=codename, content_type=ct)

        # Стандартные модельные
        p["view_user"]   = get_perm("view_user", ct_user)
        p["add_user"]    = get_perm("add_user", ct_user)
        p["change_user"] = get_perm("change_user", ct_user)
        p["delete_user"] = get_perm("delete_user", ct_user)

        p["view_sitesetup"]   = get_perm("view_sitesetup", ct_site)
        p["change_sitesetup"] = get_perm("change_sitesetup", ct_site)

        # Кастомные (из Meta.permissions у User)
        p["export_users"] = Permission.objects.get(codename="export_users", content_type=ct_user)
        p["view_finance"] = Permission.objects.get(codename="view_finance", content_type=ct_user)

        # Описание ролей -> набор прав
        roles = {
            "Admins": {
                # полный доступ к User и SiteSetup + кастомные
                "perms": {
                    p["view_user"], p["add_user"], p["change_user"], p["delete_user"],
                    p["view_sitesetup"], p["change_sitesetup"],
                    p["export_users"], p["view_finance"],
                }
            },
            "Support": {
                # поддержка: видеть и менять пользователей (без delete/add), видеть SiteSetup
                "perms": {
                    p["view_user"], p["change_user"], p["view_sitesetup"],
                }
            },
            "Finance": {
                # финансы: видеть пользователей, экспорт/финансы
                "perms": {
                    p["view_user"], p["export_users"], p["view_finance"],
                }
            },
            "Content": {
                # пока без прав — добавите позже под свои модели контента
                "perms": set()
            },
            "Admin-RO": {
                # только просмотр
                "perms": {
                    p["view_user"], p["view_sitesetup"],
                }
            },
        }

        for role_name in ROLE_NAMES:
            group, created = Group.objects.get_or_create(name=role_name)
            wanted = roles[role_name]["perms"]
            # выставляем ровно нужный набор прав
            group.permissions.set(wanted)
            group.save()
            self.stdout.write(self.style.SUCCESS(f"[OK] {role_name} — {len(wanted)} perms"))

        self.stdout.write(self.style.SUCCESS("Группы и права инициализированы."))
        self.stdout.write("Помните: для входа в админку пользователю нужны 2 вещи: is_staff=True и membership в одной из ролей.")
