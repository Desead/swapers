from __future__ import annotations

import secrets
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils import timezone, translation

from allauth.account.signals import user_logged_in, user_signed_up
try:
    from allauth.account.signals import email_confirmed
    from allauth.account.models import EmailAddress
except Exception:
    email_confirmed = None
    EmailAddress = None  # type: ignore

from .middleware import ReferralAttributionMiddleware

User = get_user_model()


# --- helpers -----------------------------------------------------------------
def _generate_ref_code(length: int = 10) -> str:
    """Компактный url-safe код (без '-' и '_')."""
    for _ in range(5):
        code = secrets.token_urlsafe(12)[:length].replace("-", "").replace("_", "")
        if not User.objects.filter(referral_code=code).exists():
            return code
    return secrets.token_urlsafe(16).replace("-", "").replace("_", "")[:16]


# --- signals -----------------------------------------------------------------
@receiver(pre_save, sender=User)
def ensure_referral_code(sender, instance: User, **kwargs):
    """
    Проставляем referral_code ПЕРЕД первым сохранением пользователя,
    чтобы не ломать unique-индекс пустыми значениями.
    """
    if not instance.pk and not instance.referral_code:
        instance.referral_code = _generate_ref_code()


@receiver(user_logged_in)
def on_user_logged_in(request, user: User, **kwargs):
    """Синхронизируем язык интерфейса после входа."""
    try:
        lang = (user.language or settings.LANGUAGE_CODE).split("-")[0]
        translation.activate(lang)
        request.LANGUAGE_CODE = lang
    except Exception:
        pass


@receiver(user_signed_up)
def bind_referral_on_signup(request, user: User, **kwargs):
    """
    При регистрации:
    - читаем реф-код из подписанной cookie или из session['referral_pending']
      (для обратной совместимости поддерживаем legacy session['ref_code'])
    - ищем партнёра по User.referral_code и связываем, если ещё не связан
    - считаем задержку до регистрации
    - просим middleware удалить cookie
    """
    if not request:
        return

    payload = (ReferralAttributionMiddleware.read_cookie(request)
               or request.session.get("referral_pending")
               or ({"code": request.session.get("ref_code")} if request.session.get("ref_code") else None))
    if not payload:
        return

    code = (payload.get("code") or "").strip()
    if not code:
        return

    # Привязка к партнёру (если ещё не привязан и не сам к себе)
    if not user.referred_by:
        partner = User.objects.filter(referral_code=code).only("id").first()
        if partner and partner.pk != user.pk:
            user.referred_by = partner

    # Метрика задержки
    first_seen_iso = payload.get("first_seen")
    first_seen_dt = None
    try:
        if first_seen_iso:
            first_seen_dt = datetime.fromisoformat(first_seen_iso)
            if timezone.is_naive(first_seen_dt):
                first_seen_dt = timezone.make_aware(first_seen_dt, timezone.utc)
    except Exception:
        first_seen_dt = None

    if first_seen_dt:
        user.referral_first_seen_at = first_seen_dt
        joined = user.date_joined or timezone.now()
        if timezone.is_naive(joined):
            joined = timezone.make_aware(joined, timezone.utc)
        user.referral_signup_delay = (joined - first_seen_dt)

    try:
        user.save(update_fields=["referred_by", "referral_first_seen_at", "referral_signup_delay"])
    except Exception:
        pass

    # попросим middleware удалить cookie на следующем ответе и очистим временные маркеры
    try:
        request.session["ref_cookie_delete"] = True
        request.session.pop("referral_pending", None)
        request.session.pop("ref_code", None)  # legacy
    except Exception:
        pass


# --- бонус после ПЕРВОГО подтверждённого e-mail --------------------------------
if email_confirmed and EmailAddress:
    @receiver(email_confirmed)
    def on_email_confirmed(request, email_address: EmailAddress, **kwargs):
        """
        Начисляем бонус «пригласившему» только после ПЕРВОГО подтверждения email у приглашённого пользователя.
        Сумма: settings.REFERRAL_BONUS_USD или Decimal('1.50') по умолчанию.
        """
        try:
            user_id = email_address.user_id

            # Бонус только за ПЕРВОЕ подтверждение email этого пользователя
            verified_count = EmailAddress.objects.filter(user_id=user_id, verified=True).count()
            if verified_count != 1:
                return

            # кто пригласил
            referrer_id = (
                User.objects.filter(pk=user_id)
                .values_list("referred_by_id", flat=True)
                .first()
            )
            if not referrer_id:
                return

            bonus = getattr(settings, "REFERRAL_BONUS_USD", Decimal("1.50"))
            User.objects.filter(pk=referrer_id).update(
                count=F("count") + 1,
                balance=F("balance") + bonus,
            )
        except Exception:
            return
