def axes_get_username(request, credentials):
    """
    Универсально вынимаем логин из разных форм:
    - allauth: 'login'
    - админка Django: 'username'
    - возможный сценарий: 'email'
    """
    return (
        (credentials or {}).get("login")
        or (credentials or {}).get("username")
        or (credentials or {}).get("email")
        or ""
    )
