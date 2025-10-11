"""
Автовыбор настроек до первого импорта settings.

Логика:
- Если существует файл-сентинил swapers/USE_PROD → грузим prod-настройки.
- Иначе — dev.

Никаких переменных окружения не используем.
"""

from pathlib import Path
from importlib import import_module as _imp

_BASE = Path(__file__).resolve().parent
# Файл-сентинил лежит рядом с пакетом: swapers/USE_PROD
_SENTINEL = _BASE.parent / "USE_PROD"

USE_PROD = _SENTINEL.exists()

# Импортируем выбранный модуль и прокидываем его UPPERCASE-настройки в текущий namespace
_mod = _imp(".prod" if USE_PROD else ".dev", __package__)
for _k, _v in _mod.__dict__.items():
    if _k.isupper():
        globals()[_k] = _v
