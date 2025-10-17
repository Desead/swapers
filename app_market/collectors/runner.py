# app_market/collectors/runner.py
from __future__ import annotations

import argparse
import importlib
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

def _configure_logging(verbose: int):
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

log = logging.getLogger(__name__)

def _ensure_django():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE", "swapers.settings.dev"))
    import django
    django.setup()

def _load_class(dotted: str):
    """
    dotted = 'pkg.mod:ClassName'
    Никаких догадок: жёстко грузим модуль и берём класс.
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
    if only:
        for name in only:
            entry = cfg.get(name)
            if entry and entry.get("enabled", True):
                yield name, entry
        return
    for name, entry in cfg.items():
        if entry.get("enabled", True):
            yield name, entry

def _sleep_with_jitter(base_seconds: int):
    jitter = random.uniform(0.05, 0.25) * base_seconds
    time.sleep(base_seconds + jitter)

def run_once(*, providers: Optional[List[str]], task: str, dump_raw: bool, admin_mirror: bool) -> int:
    """
    Последовательный запуск выбранной задачи по включённым провайдерам.
    НИЧЕГО не берём из collectors.registry — только настройки.
    """
    from django.conf import settings
    from .tasks import run_prices, run_stats, run_wallet_assets

    cfg: Dict[str, Dict[str, Any]] = getattr(settings, "COLLECTORS_PROVIDER_REGISTRY", {})
    if not cfg:
        log.error("COLLECTORS_PROVIDER_REGISTRY is empty — nothing to run")
        return 0

    ok = 0
    base_dir: Path = getattr(settings, "BASE_DIR", Path.cwd())

    for prov, entry in _iter_enabled_providers(cfg, providers):
        path = entry.get("path")
        needs_api = bool(entry.get("needs_api", False))

        # 1) Создание адаптера
        adapter = None
        try:
            cls = _load_class(path)
            if needs_api:
                try:
                    from .credentials import get as get_credentials
                    creds = get_credentials(prov)  # может вернуть None — это нормально
                except Exception:
                    log.exception("Credentials: unexpected error for %s", prov)
                    creds = None
                try:
                    adapter = cls(credentials=creds)
                except TypeError:
                    adapter = cls()
            else:
                adapter = cls()
            log.info("Adapter ready: %s (%s)", prov, path)
        except Exception:
            log.exception("Adapter init failed for %s (%s)", prov, path)
            continue

        # 2) Выполнение задач
        def _do_wallet():
            nonlocal ok
            try:
                run_wallet_assets(provider=prov, adapter=adapter, dump_raw=dump_raw)
                ok += 1
            except Exception:
                log.exception("WalletAssetsTask failed for %s", prov)

        def _do_prices():
            nonlocal ok
            try:
                run_prices(provider=prov, dump_raw=dump_raw, mirror_to_admin=admin_mirror)
                ok += 1
            except Exception:
                log.exception("PricesTask failed for %s", prov)

        def _do_stats():
            nonlocal ok
            try:
                run_stats(provider=prov, dump_raw=dump_raw)
                ok += 1
            except Exception:
                log.exception("StatsTask failed for %s", prov)

        if task == "wallet-assets":
            _do_wallet()
        elif task == "prices":
            _do_prices()
        elif task == "stats":
            _do_stats()
        else:  # all
            _do_wallet()
            _sleep_with_jitter(1)
            _do_prices()
            _sleep_with_jitter(1)
            _do_stats()

    return ok

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Unified collectors runner (settings-driven)")
    parser.add_argument("--provider", action="append", help="Provider code (repeatable). Default: all enabled")
    parser.add_argument("--task", choices=("wallet-assets", "prices", "stats", "all"), default="all")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--loop", action="store_true", help="Run forever with settings intervals")
    parser.add_argument("--dump-raw", action="store_true", help="Dump raw JSON once per day")
    parser.add_argument("--admin-mirror", action="store_true", help="Mirror L1 prices to admin (PriceL1)")
    parser.add_argument("-v", "--verbose", action="count", default=0)

    args = parser.parse_args(argv or sys.argv[1:])
    _configure_logging(args.verbose)
    _ensure_django()

    if args.once and args.loop:
        parser.error("Use either --once or --loop, not both.")

    if args.once or not args.loop:
        return 0 if run_once(
            providers=args.provider, task=args.task, dump_raw=args.dump_raw, admin_mirror=args.admin_mirror
        ) else 1

    # loop-режим (используем интервалы из настроек)
    from django.conf import settings
    prices_iv = int(getattr(settings, "COLLECTORS_PRICES_INTERVAL_S", 10))
    wallet_iv = int(getattr(settings, "COLLECTORS_WALLET_INTERVAL_S", 3600))
    try:
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
