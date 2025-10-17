from __future__ import annotations
import json
from pathlib import Path
from typing import Any

# Не трогаем settings на уровне модуля → берём при вызове.
def _root_dir() -> Path:
    try:
        from django.conf import settings
        base = Path(getattr(settings, "BASE_DIR", Path.cwd()))
        return Path(getattr(settings, "COLLECTORS_DUMP_ROOT", base / "logs" / "raw"))
    except Exception:
        return Path.cwd() / "logs" / "raw"

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _single_path(prefix: str, provider: str) -> Path:
    # единый файл на провайдера и тип
    return _root_dir() / f"{prefix.lower()}-{provider.lower()}.json"

def write_daily_dump(prefix: str, provider: str, payload: Any) -> Path | None:
    """
    Пишем ОДИН файл на провайдера и тип (wallet/prices/stats).
    Если файл уже существует — НИЧЕГО не делаем.
    Путь: logs/raw/<prefix>-<provider>.json (COLLECTORS_DUMP_ROOT переопределяет корень).
    """
    path = _single_path(prefix, provider)
    if path.exists():
        return None
    _ensure_dir(path.parent)
    # Decimal/datetime и т.п. сериализуем строкой
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return path
