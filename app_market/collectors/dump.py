from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from typing import Any

# ВАЖНО: не трогаем settings на уровне модуля → берём при вызове.
def _root_dir() -> Path:
    try:
        from django.conf import settings
        base = Path(getattr(settings, "BASE_DIR", Path.cwd()))
        return Path(getattr(settings, "COLLECTORS_DUMP_ROOT", base / "log" / "raw"))
    except Exception:
        return Path.cwd() / "log" / "raw"

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _daily_path(prefix: str, provider: str) -> Path:
    day = datetime.utcnow().strftime("%Y-%m-%d")
    return _root_dir() / day / f"{prefix.lower()}-{provider.lower()}.json"

def write_daily_dump(prefix: str, provider: str, payload: Any) -> Path | None:
    """
    Пишем один файл в сутки на провайдера и тип (wallet/prices/stats).
    Если файл уже существует — НИЧЕГО не делаем (по требованию).
    """
    path = _daily_path(prefix, provider)
    if path.exists():
        return None
    _ensure_dir(path.parent)
    # json pretty для человекочтения
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return path
