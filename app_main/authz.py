from functools import wraps
from django.core.exceptions import PermissionDenied

# Можно импортировать из swapers.admin, чтобы не дублировать
ALLOWED_ADMIN_GROUPS = {"Admins", "Support", "Finance", "Content", "Admin-RO"}

def user_in_groups(user, groups: set[str]) -> bool:
    return user.is_authenticated and user.groups.filter(name__in=groups).exists()

def role_required(*group_names: str):
    """
    Декоратор для FBV: @role_required("Finance") / @role_required("Admins","Support")
    """
    groups = set(group_names)
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if user.is_superuser or user_in_groups(user, groups):
                return view_func(request, *args, **kwargs)
            raise PermissionDenied
        return _wrapped
    return decorator
