# tests/test_settings_router.py
import importlib
import importlib.util
import sys
from pathlib import Path

def reload_settings():
    # чистим любой уже импортированный вариант настроек
    for mod in list(sys.modules):
        if mod == "swapers.settings" or mod.startswith("swapers.settings."):
            del sys.modules[mod]
    return importlib.import_module("swapers.settings")

def get_swapers_dir() -> Path:
    # находим фактический путь к пакету swapers независимо от места запуска тестов
    spec = importlib.util.find_spec("swapers")
    assert spec and spec.submodule_search_locations, "Package 'swapers' not found"
    return Path(next(iter(spec.submodule_search_locations)))

def test_dev_by_default(tmp_path):
    # без USE_PROD → dev
    pkg_dir = get_swapers_dir()
    use_prod = pkg_dir / "USE_PROD"
    if use_prod.exists():
        use_prod.unlink()

    s = reload_settings()
    assert s.DEBUG is True
    assert s.DATABASES["default"]["ENGINE"].endswith("sqlite3")

def test_prod_with_sentinel(tmp_path):
    pkg_dir = get_swapers_dir()
    use_prod = pkg_dir / "USE_PROD"
    # гарантируем существование папки (на всякий случай)
    use_prod.parent.mkdir(parents=True, exist_ok=True)
    use_prod.write_text("")  # создать маркер

    try:
        s = reload_settings()
        assert s.DEBUG is False
        assert s.DATABASES["default"]["ENGINE"].endswith("postgresql")
    finally:
        # вернуть систему к исходному виду
        if use_prod.exists():
            use_prod.unlink()
