# app_market/collectors/dump.py
from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

log = logging.getLogger(__name__)

def _safe_base_dir() -> Path:
    """
    Возвращает BASE_DIR из настроек, если Django сконфигурирован.
    Иначе — текущий каталог проекта (cwd).
    """
    try:
        base_dir = getattr(settings, "BASE_DIR")  # триггерит ImproperlyConfigured, если не готово
        if isinstance(base_dir, (str, Path)):
            return Path(base_dir)
    except ImproperlyConfigured:
        pass
    return Path.cwd()

def _raw_root() -> Path:
    base_dir = _safe_base_dir()
    default_root = base_dir / "log" / "raw"
    try:
        root = getattr(settings, "COLLECTORS_DUMP_ROOT", default_root)
        return Path(root)
    except ImproperlyConfigured:
        return default_root

@contextmanager
def _file_lock(lock_path: Path):
    lock_fd = None
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(lock_fd, b"1")
        yield
    except FileExistsError:
        # уже пишется кем-то — тихо выходим
        yield
    finally:
        try:
            if lock_fd is not None:
                os.close(lock_fd)
                lock_path.unlink(missing_ok=True)
        except Exception:
            pass

def write_daily_dump(provider: str, task: str, payload: Any, *, date: Optional[datetime] = None) -> Optional[Path]:
    """
    Сохраняет сырой ответ API в файл за сутки один раз.
    Если файл уже есть — НИЧЕГО не делает (возвращает None).
    """
    date = date or datetime.utcnow()
    dir_path = _raw_root() / provider.lower() / task.replace("_", "-")
    dir_path.mkdir(parents=True, exist_ok=True)

    file_path = dir_path / f"{date.strftime('%Y-%m-%d')}.json"
    if file_path.exists():
        return None

    lock_path = file_path.with_suffix(".lock")
    with _file_lock(lock_path):
        if file_path.exists():
            return None
        try:
            with file_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            log.info("Dump written: %s", file_path)
            return file_path
        except Exception as e:
            log.exception("Failed to write dump %s: %s", file_path, e)
            try:
                file_path.unlink(missing_ok=True)
            finally:
                return None
