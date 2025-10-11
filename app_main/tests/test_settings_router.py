# tests/test_settings_router.py
import importlib, sys
from pathlib import Path

def reload_settings():
    if "swapers.settings" in sys.modules:
        del sys.modules["swapers.settings"]
    return importlib.import_module("swapers.settings")

def test_dev_by_default(tmp_path, monkeypatch):
    # без USE_PROD → dev
    pkg_dir = Path(__file__).resolve().parents[1] / "swapers"
    use_prod = pkg_dir / "USE_PROD"
    if use_prod.exists(): use_prod.unlink()

    s = reload_settings()
    assert s.DEBUG is True
    assert s.DATABASES["default"]["ENGINE"].endswith("sqlite3")

def test_prod_with_sentinel(tmp_path):
    pkg_dir = Path(__file__).resolve().parents[1] / "swapers"
    use_prod = pkg_dir / "USE_PROD"
    use_prod.write_text("")  # создать маркер

    try:
        s = reload_settings()
        assert s.DEBUG is False
        assert s.DATABASES["default"]["ENGINE"].endswith("postgresql")
    finally:
        use_prod.unlink()
