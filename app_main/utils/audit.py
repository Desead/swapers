# app_main/utils/audit.py
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from django.utils import timezone

# Поля, которые маскируем (секреты)
MASK_FIELDS = {
    "email_host_password",
    "telegram_bot_token",
}

# Поля, которые хешируем вместо вывода «как есть» (слишком длинные/чувствительные)
HASH_FIELDS = {
    "robots_txt",
    "head_inject_html",
}

# Поля, которые игнорируем в диффе (технические/авто-поля)
IGNORED_FIELDS = {
    "updated_at",
    "singleton",
}

# критичные поля (красный значок)
CRITICAL_FIELDS = {
    "fee_percent",
    "admin_path",
    "block_indexing",
    "maintenance_mode",
    "use_https_in_meta",
    "ref_attribution_window_days",
}

# важные поля (оранжевый значок)
IMPORTANT_FIELDS = {
    "email_host",
    "email_port",
    "email_host_user",
    "email_use_tls",
    "email_use_ssl",
    "email_from",
    "telegram_chat_id",
    "hreflang_enabled",
    "jsonld_enabled",
}

# всё остальное — info


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    try:
        return str(v)
    except Exception:
        return repr(v)


def _mask_secret(v: Any) -> str:
    s = _as_str(v)
    if not s:
        return ""
    tail = s[-4:] if len(s) > 4 else s
    return f"***{tail}"


def _hash_text(v: Any) -> str:
    s = _as_str(v)
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]
    return f"hash:{h}"


def diff_sitesetup(old: Any, new: Any, labels: Dict[str, str]) -> List[Tuple[str, str, str]]:
    """
    Вернёт список (field, old_str, new_str) только для реально изменённых полей.
    labels — карта для красивого имени поля (verbose_name).
    Игнорируем технические поля (см. IGNORED_FIELDS).
    """
    changed: List[Tuple[str, str, str]] = []

    # сравним только реальные model fields, исключая игнорируемые
    field_names = [f.name for f in new._meta.fields if f.name not in IGNORED_FIELDS]

    for name in field_names:
        old_val = getattr(old, name, None) if old else None
        new_val = getattr(new, name, None)

        # нормализуем файлы: показываем только имя
        if hasattr(old_val, "name"):
            old_val = old_val.name
        if hasattr(new_val, "name"):
            new_val = new_val.name

        if old is None:
            # создание — пропускаем (singleton уже существует), нас интересуют изменения
            continue

        if old_val == new_val:
            continue

        # маскировка/хеширование
        if name in MASK_FIELDS:
            old_s = _mask_secret(old_val)
            new_s = _mask_secret(new_val)
        elif name in HASH_FIELDS:
            old_s = _hash_text(old_val)
            new_s = _hash_text(new_val)
        else:
            old_s = _as_str(old_val)
            new_s = _as_str(new_val)

        # короткая «косметика» для пустых
        old_s = old_s if old_s != "" else "—"
        new_s = new_s if new_s != "" else "—"

        changed.append((name, old_s, new_s))

    return changed


def severity_for_fields(names: List[str]) -> str:
    """
    Вернёт 'critical' / 'important' / 'info', исходя из набора изменённых полей.
    """
    name_set = set(names)
    if name_set & CRITICAL_FIELDS:
        return "critical"
    if name_set & IMPORTANT_FIELDS:
        return "important"
    return "info"


def headline_emoji(level: str) -> str:
    return {
        "critical": "🔴",
        "important": "🟠",
        "info": "🔵",
    }.get(level, "🔵")


def format_telegram_message(user_email: str, ip: str, ua: str, changes: List[Tuple[str, str, str]], labels: Dict[str, str]) -> Tuple[str, str]:
    """
    Формирует (level, message_html) для Telegram.
    """
    names = [n for n, _, _ in changes]
    level = severity_for_fields(names)
    icon = headline_emoji(level)
    ts = timezone.now().strftime("%Y-%m-%d %H:%M:%S %z")

    # Соберём тело
    lines = []
    for name, old_s, new_s in changes:
        label = labels.get(name, name)
        # лёгкая защита от очень длинных строк
        if len(old_s) > 120:
            old_s = old_s[:117] + "…"
        if len(new_s) > 120:
            new_s = new_s[:117] + "…"
        lines.append(f"<b>{label}</b>: <code>{old_s}</code> → <code>{new_s}</code>")

    info = (
        f"{icon} <b>SiteSetup изменён</b>\n"
        f"Пользователь: <code>{user_email or 'unknown'}</code>\n"
        f"IP: <code>{ip or '-'}</code>\n"
        f"UA: <code>{(ua or '-')[:160]}</code>\n"
        f"Время: <code>{ts}</code>\n\n"
        + "\n".join(lines)
    )
    return level, info
