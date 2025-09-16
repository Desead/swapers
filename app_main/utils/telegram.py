# app_main/utils/telegram.py
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from html import escape as html_escape


def send_telegram_message(bot_token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """
    Простая отправка в Telegram Bot API без сторонних зависимостей.
    Возвращает True при успехе, False при любой ошибке (не бросает исключений).
    """
    if not bot_token or not chat_id or not text:
        return False

    # Telegram поддерживает parse_mode = "HTML" — используем его
    # ВАЖНО: экранируй текст заранее, если вставляешь пользовательские значения
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(api_url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
        try:
            js = json.loads(raw.decode("utf-8"))
            return bool(js.get("ok"))
        except Exception:
            return False
    except Exception:
        return False


def esc(s: str) -> str:
    """Экранируем для HTML-режима Telegram."""
    return html_escape(s or "", quote=False)
