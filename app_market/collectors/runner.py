from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────────────
# ЛОГИРОВАНИЕ / DJANGO
# ──────────────────────────────────────────────────────────────────────────────

def _configure_logging(verbose: int):
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

log = logging.getLogger(__name__)

def _ensure_django(settings_module: Optional[str], *, require_non_debug: bool = False):
    """
    Не гадаем модуль настроек.
    - Если передали --settings, используем его.
    - Если нет — требуем DJANGO_SETTINGS_MODULE в окружении.
    После setup() логируем DEBUG и (опционально) отказываемся работать при DEBUG=True.
    """
    if settings_module:
        os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
    if "DJANGO_SETTINGS_MODULE" not in os.environ:
        raise SystemExit(
            "DJANGO_SETTINGS_MODULE is not set. "
            "Pass --settings swapers.settings.dev|swapers.settings.prod "
            "or export DJANGO_SETTINGS_MODULE in the environment."
        )

    import django
    django.setup()

    from django.conf import settings as dj_settings
    log.info("Using settings: %s (DEBUG=%s)", os.environ["DJANGO_SETTINGS_MODULE"], dj_settings.DEBUG)

    if require_non_debug and dj_settings.DEBUG:
        raise SystemExit("Refusing to run with DEBUG=True while --require-non-debug is set.")


# ──────────────────────────────────────────────────────────────────────────────
# ФАЙЛОВЫЙ ЛОК (POSIX)
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def _file_lock(path: Path):
    """
    Эксклюзивный неблокирующий лок на файл. Если занят — бросаем SystemExit.
    """
    import fcntl  # POSIX
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit(f"Another collectors run is in progress (lock: {path}).")
    try:
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


# ──────────────────────────────────────────────────────────────────────────────
# УТИЛИТЫ
# ──────────────────────────────────────────────────────────────────────────────

def _load_class(dotted: str):
    """
    dotted = 'pkg.mod:ClassName' — жёсткая загрузка без эвристик.
    """
    if ":" not in dotted:
        raise ValueError(f"Invalid dotted path '{dotted}', expected 'module:Class'")
    mod_name, cls_name = dotted.split(":", 1)
    module = importlib.import_module(mod_name)
    try:
        return getattr(module, cls_name)
    except AttributeError as e:
        raise AttributeError(f"Class '{cls_name}' not found in module '{mod_name}'") from e


def _iter_enabled_providers(cfg: Dict[str, Dict[str, Any]], only: Optional[List[str]]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    """
    Итерация по провайдерам в порядке:
      - если указан фильтр 'only' — в том же порядке, что и в списке 'only';
      - иначе — по всем enabled в словаре cfg.
    """
    if only:
        for code in only:
            entry = cfg.get(code)
            if entry and entry.get("enabled", True):
                yield code, entry
        return
    for code, entry in cfg.items():
        if entry.get("enabled", True):
            yield code, entry


# ──────────────────────────────────────────────────────────────────────────────
# ОСНОВНОЙ ЗАПУСК
# ──────────────────────────────────────────────────────────────────────────────

def run_once(*, providers: Optional[List[str]], task: str, dump_raw: bool, admin_mirror: bool) -> int:
    """
    Последовательный запуск выбранной задачи по включённым провайдерам.
    Ничего не берём из registry-модулей — только из настроек.
    """
    from django.conf import settings
    from .tasks import run_prices, run_stats, run_wallet_assets

    # Строго берём реестр из настроек; если отсутствует — это ошибка конфигурации.
    try:
        cfg: Dict[str, Dict[str, Any]] = settings.COLLECTORS_PROVIDER_REGISTRY  # type: ignore[attr-defined]
    except AttributeError:
        log.error("Missing settings.COLLECTORS_PROVIDER_REGISTRY")
        return 0
    if not isinstance(cfg, dict) or not cfg:
        log.error("COLLECTORS_PROVIDER_REGISTRY is empty or invalid — nothing to run")
        return 0

    ok = 0

    for prov, entry in _iter_enabled_providers(cfg, providers):
        # path — обязательный ключ, без .get()
        try:
            path = entry["path"]
        except KeyError:
            log.error("Provider '%s' misconfigured: 'path' is required", prov)
            continue
        needs_api = bool(entry.get("needs_api", False))

        # 0) Если нужны ключи — достаём заранее и скипаем при отсутствии
        creds = None
        if needs_api:
            try:
                from .credentials import get as get_credentials
                creds = get_credentials(prov)  # может вернуть None
            except Exception:
                log.exception("Credentials: unexpected error for %s", prov)
                creds = None
            if creds is None:
                log.error("Skipping %s: credentials required (needs_api=True) but not found.", prov)
                continue

        # 1) Создание адаптера
        try:
            cls = _load_class(path)
            try:
                adapter = cls(credentials=creds) if needs_api else cls()
            except TypeError:
                # адаптер без параметров
                adapter = cls()
            log.info("Adapter ready: %s (%s)", prov, path)
        except Exception:
            log.exception("Adapter init failed for %s (%s)", prov, path)
            continue

        # 2) Выполнение задач (строго и просто)
        try:
            if task == "wallet-assets":
                run_wallet_assets(provider=prov, adapter=adapter, dump_raw=dump_raw)
                ok += 1
            elif task == "prices":
                run_prices(provider=prov, dump_raw=dump_raw, mirror_to_admin=admin_mirror)
                ok += 1
            elif task == "stats":
                run_stats(provider=prov, dump_raw=dump_raw)
                ok += 1
            else:  # all
                run_wallet_assets(provider=prov, adapter=adapter, dump_raw=dump_raw)
                time.sleep(0.5)  # минимальная пауза, чтобы не «стрелять очередями» вплотную
                run_prices(provider=prov, dump_raw=dump_raw, mirror_to_admin=admin_mirror)
                time.sleep(0.5)
                run_stats(provider=prov, dump_raw=dump_raw)
                ok += 3
        except Exception:
            log.exception("Task '%s' failed for %s", task, prov)
            # продолжаем к следующему провайдеру

    return ok


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Unified collectors runner (settings-driven)")
    parser.add_argument("--settings", help="Django settings module, e.g. swapers.settings.dev or swapers.settings.prod")
    parser.add_argument("--require-non-debug", action="store_true", help="Abort if DEBUG=True (safety for prod)")
    parser.add_argument("--provider", action="append", help="Provider code (repeatable). Default: all enabled")
    parser.add_argument("--task", choices=("wallet-assets", "prices", "stats", "all"), default="all")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--loop", action="store_true", help="Run forever with settings intervals")
    parser.add_argument("--dump-raw", action="store_true", help="Dump raw JSON once (single file per provider/type)")
    parser.add_argument("--admin-mirror", action="store_true", help="Mirror L1 prices to admin (PriceL1)")
    parser.add_argument("-v", "--verbose", action="count", default=0)

    args = parser.parse_args(argv or sys.argv[1:])
    _configure_logging(args.verbose)
    _ensure_django(args.settings, require_non_debug=args.require_non_debug)

    # Подготавливаем лок-файл после инициализации Django (нужен BASE_DIR)
    from django.conf import settings
    lock_path = Path(settings.BASE_DIR) / "var" / "collectors.lock"

    if args.once and args.loop:
        parser.error("Use either --once or --loop, not both.")

    if args.once or not args.loop:
        with _file_lock(lock_path):
            return 0 if run_once(
                providers=args.provider, task=args.task, dump_raw=args.dump_raw, admin_mirror=args.admin_mirror
            ) else 1

    # loop-режим: интервалы строго из настроек
    try:
        prices_iv = int(settings.COLLECTORS_PRICES_INTERVAL_S)         # type: ignore[attr-defined]
        wallet_iv = int(settings.COLLECTORS_WALLET_INTERVAL_S)         # type: ignore[attr-defined]
    except AttributeError as e:
        log.error("Missing interval settings: %s", e)
        return 1

    try:
        with _file_lock(lock_path):
            while True:
                rc = run_once(
                    providers=args.provider, task=args.task, dump_raw=args.dump_raw, admin_mirror=args.admin_mirror
                )
                if args.task == "wallet-assets":
                    time.sleep(wallet_iv)
                elif args.task == "prices":
                    time.sleep(prices_iv)
                elif args.task == "stats":
                    time.sleep(max(300, wallet_iv))
                else:
                    time.sleep(5)
    except KeyboardInterrupt:
        log.info("Interrupted.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
