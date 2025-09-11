from base64 import b64encode
from io import BytesIO

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.urls import reverse
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice
import qrcode
from django.conf import settings
from app_main.services.site_setup import get_site_setup


@login_required
@staff_member_required
def twofa_setup(request):
    """
    Мастер подключения TOTP для сотрудников.
    1) Если уже есть confirmed-устройство — просто показываем статус.
    2) Иначе создаём “черновик” устройства, показываем QR и просим ввести код.
    """
    user = request.user

    confirmed = TOTPDevice.objects.filter(user=user, confirmed=True).first()
    if confirmed:
        return render(request, "security/2fa_setup.html", {"already_enabled": True})

    device = TOTPDevice.objects.filter(user=user, confirmed=False).first()
    if not device:
        device = TOTPDevice.objects.create(user=user, name="Authenticator", confirmed=False)

    # otpauth URI -> QR (использует OTP_TOTP_ISSUER из settings)
    settings.OTP_TOTP_ISSUER = get_site_setup().otp_issuer
    otpauth_url = device.config_url
    qr = qrcode.make(otpauth_url)
    buf = BytesIO()
    qr.save(buf, format="PNG")
    qr_b64 = b64encode(buf.getvalue()).decode("ascii")

    if request.method == "POST":
        token = (request.POST.get("token") or "").strip().replace(" ", "")
        if device.verify_token(token):
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            # пометить текущую сессию как “верифицированную” по OTP
            otp_login(request, device)
            messages.success(request, "Двухфакторная аутентификация включена.")
            return redirect(reverse("admin:index"))
        else:
            messages.error(request, "Неверный код. Попробуйте ещё раз.")

    return render(request, "security/2fa_setup.html", {
        "already_enabled": False,
        "qr_b64": qr_b64,
    })
