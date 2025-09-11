from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import logout
from .forms import AccountForm


def home(request):
    return render(request, "home.html")


@login_required
def dashboard(request):
    # ссылка вида https://site.tld/?ref=CODE
    ref_link = None
    if getattr(request.user, "referral_code", ""):
        base = request.build_absolute_uri("/")
        ref_link = f"{base}?ref={request.user.referral_code}"
    return render(request, "dashboard.html", {
        "user_obj": request.user,
        "ref_link": ref_link,
    })


@login_required
def account_settings(request):
    user = request.user
    if request.method == "POST":
        form = AccountForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "Настройки сохранены.")
            return redirect("account_settings")
        messages.error(request, "Проверьте форму — есть ошибки.")
    else:
        form = AccountForm(instance=user)

    return render(request, "account_settings.html", {"form": form})


@login_required
def account_delete(request):
    """
    Самоудаление аккаунта с подтверждением пароля.
    Удаление суперпользователя запрещено из интерфейса.
    """
    user = request.user

    if user.is_superuser:
        messages.error(request, "Удаление суперпользователя запрещено из интерфейса. Используйте админку.")
        return redirect("account_settings")

    if request.method == "POST":
        password = request.POST.get("password", "")
        confirm = request.POST.get("confirm_text", "").strip()

        if confirm != "DELETE":
            messages.error(request, "Подтверждение не совпало. Введите слово DELETE.")
            return redirect("account_delete")

        if not user.check_password(password):
            messages.error(request, "Неверный пароль.")
            return redirect("account_delete")

        email = user.email
        logout(request)
        user.delete()
        messages.success(request, f"Аккаунт {email} удалён.")
        return redirect("home")

    return render(request, "account/account_delete.html")
