import secrets
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.conf import settings

from app_main.models import SiteSetup

# allauth: сигналы и модель EmailAddress
try:
    from allauth.account.signals import user_signed_up, email_confirmed
    from allauth.account.models import EmailAddress
except Exception:
    user_signed_up = None
    email_confirmed = None
    EmailAddress = None

User = get_user_model()


@receiver(post_save, sender=User)
def ensure_superuser_verified_email(sender, instance: User, **kwargs):
    """
    Для суперпользователей авто-создаём/обновляем EmailAddress как verified+primary.
    Работает и при создании, и при изменении e-mail суперпользователя.
    """
    if not EmailAddress:
        return
    if not instance.is_superuser:
        return
    if not instance.email:
        return

    ea, created = EmailAddress.objects.get_or_create(
        user=instance,
        email=instance.email,
        defaults={"verified": True, "primary": True},
    )
    # если запись была, убеждаемся что она отмечена как verified+primary
    changed = False
    if not ea.verified:
        ea.verified = True
        changed = True
    if not ea.primary:
        ea.primary = True
        changed = True
    if changed:
        ea.save(update_fields=["verified", "primary"])

    # все остальные адреса у этого пользователя — не primary
    EmailAddress.objects.filter(user=instance).exclude(pk=ea.pk).update(primary=False)


# --- генерация партнёрского кода при создании пользователя ---

def _generate_ref_code(length: int = 10) -> str:
    """
    Компактный url-safe код. Убираем '-' и '_' для красоты.
    Проверка уникальности будет сделана вне этого хелпера.
    """
    for _ in range(5):
        code = secrets.token_urlsafe(12)[:length].replace("-", "").replace("_", "")
        if not User.objects.filter(referral_code=code).exists():
            return code
    # в крайне редком случае коллизий — подлиннее
    return secrets.token_urlsafe(16).replace("-", "").replace("_", "")[:16]


@receiver(post_save, sender=User)
def ensure_referral_code(sender, instance, created, **kwargs):
    """
    Проставляем referral_code один раз после создания пользователя.
    """
    if created and not instance.referral_code:
        instance.referral_code = _generate_ref_code()
        instance.save(update_fields=["referral_code"])


# --- фиксируем «кто привёл» в момент регистрации (без начислений) ---

if user_signed_up:
    @receiver(user_signed_up)
    def on_user_signed_up(request, user, **kwargs):
        """
        После успешной регистрации (до подтверждения email):
        достаём ref_code из сессии, сохраняем user.referred_by.
        НИКАКИХ начислений тут не делаем.
        """
        try:
            ref_code = request.session.pop("ref_code", None)
        except Exception:
            ref_code = None
        if not ref_code:
            return

        referrer = User.objects.filter(referral_code=ref_code).only("id").first()
        if not referrer:
            return
        if referrer.id == user.id:
            # сам себя «привёл» — игнорируем
            return

        # Привязываем однократно и без гонок
        User.objects.filter(pk=user.pk, referred_by__isnull=True).update(referred_by=referrer)

# --- начисляем бонус только после ПЕРВОГО подтверждённого email ---

if email_confirmed and EmailAddress:
    @receiver(email_confirmed)
    def on_email_confirmed(request, email_address, **kwargs):
        # Берём ID пользователя из адреса, а ссылку на пригласителя читаем СВЕЖУЮ из БД,
        # чтобы не попасть на устаревший инстанс user.
        user_id = email_address.user_id
        referrer_id = (
            User.objects.filter(pk=user_id)
            .values_list("referred_by_id", flat=True)
            .first()
        )
        if not referrer_id:
            return

        # Бонус только за ПЕРВОЕ подтверждение email этого пользователя
        try:
            verified_count = EmailAddress.objects.filter(user_id=user_id, verified=True).count()
        except Exception:
            return
        if verified_count != 1:
            return

        BONUS = Decimal("1.50")
        with transaction.atomic():
            User.objects.filter(pk=referrer_id).update(
                count=F("count") + 1,
                balance=F("balance") + BONUS,
            )


# --- инвалидация кэша SiteSetup и обновление issuer для 2FA на лету ---
@receiver(post_save, sender=SiteSetup)
def invalidate_site_setup_cache(sender, instance, **kwargs):
    cache.delete("site_setup_singleton")
    # На текущем процессе сразу обновим имя сервиса для TOTP
    try:
        settings.OTP_TOTP_ISSUER = instance.otp_issuer
    except Exception:
        pass
