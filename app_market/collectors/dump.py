# app_market/collectors/dump.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from django.conf import settings


def _root_dir() -> Path:
    """
    Корень для сырых дампов.
    - COLLECTORS_DUMP_ROOT → обязателен к чтению напрямую;
    - если отсутствует в настройках, берём BASE_DIR/logs/raw (прямой доступ к BASE_DIR).
    """
    # settings должен быть инициализирован раннером; если нет — пусть падает явно.
    base = Path(settings.BASE_DIR)
    try:
        return Path(settings.COLLECTORS_DUMP_ROOT)
    except AttributeError:
        return base / "logs" / "raw"


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _single_path(prefix: str, provider: str) -> Path:
    # единый файл на провайдера и тип
    return _root_dir() / f"{prefix.lower()}-{provider.lower()}.json"


def write_daily_dump(prefix: str, provider: str, payload: Any) -> Path | None:
    """
    Пишем ОДИН файл на провайдера и тип (wallet/prices/stats).
    Если файл уже существует — НИЧЕГО не делаем.
    Путь: <COLLECTORS_DUMP_ROOT>/<prefix>-<provider>.json.
    """
    path = _single_path(prefix, provider)
    if path.exists():
        return None
    _ensure_dir(path.parent)
    # Decimal/datetime и пр. сериализуем в строку
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return path
