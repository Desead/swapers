# app_market/collectors/runner.py
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional

def _configure_logging(verbose: int):
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

log = logging.getLogger(__name__)

def _ensure_django():
    """
    Готовим Django до любых импортов модулей, которые обращаются к settings.
    """
    # Если переменная не задана, по умолчанию берём dev-настройки проекта
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE", "swapers.settings.dev"))
    import django  # импорт только после установки переменной
    django.setup()

def _provider_lock_path(provider: str, base_dir: Path) -> Path:
    base = base_dir / "log" / "locks"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{provider.lower()}.lock"

def _with_file_lock(lock_path: Path, fn):
    try:
        fd = lock_path.open("x")
    except FileExistsError:
        log.info("Provider lock busy: %s", lock_path)
        return False
    try:
        try:
            fn()
            return True
        finally:
            fd.close()
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass

def _sleep_with_jitter(base_seconds: int):
    jitter = random.uniform(0.05, 0.25) * base_seconds
    time.sleep(base_seconds + jitter)

def run_once(*, providers: Optional[List[str]], task: str, dump_raw: bool, admin_mirror: bool) -> int:
    """
    Запускает выбранную задачу последовательно по провайдерам.
    Внутри провайдера выполняем цепочку (wallet->prices->stats) если task == "all".
    """
    # Импорты после django.setup()
    from django.conf import settings
    from .registry import get_entry, make_adapter, REGISTRY
    from .sinks import PricesAdminMirror, PricesRedisSink, VoidSink, WalletDBSink
    from .tasks import run_prices, run_stats, run_wallet_assets
    from .metrics import Counter
    from .schedules import wallet_interval_seconds, prices_interval_seconds

    def _iterate_providers(selected: Optional[List[str]]) -> Iterable[str]:
        if selected:
            for p in selected:
                yield p
            return
        if REGISTRY:
            for name, entry in REGISTRY.items():
                if entry.enabled:
                    yield name
            return
        cfg = getattr(settings, "COLLECTORS_PROVIDER_REGISTRY", {})
        for name, entry in cfg.items():
            if entry.get("enabled", True):
                yield name

    ok = 0
    base_dir: Path = getattr(settings, "BASE_DIR", Path.cwd())

    for prov in _iterate_providers(providers):
        def worker():
            nonlocal ok
            entry = get_entry(prov)

            # Креды подтянем лениво, только если нужны
            creds = None
            if entry.needs_api_key:
                from .credentials import get as get_credentials
                creds = get_credentials(prov)

            adapter = make_adapter(prov, credentials=creds)
            log.info("Adapter ready: %s (%s)", prov, entry.dotted_path)

            # Синки/метрики
            wallet_sink = WalletDBSink()
            prices_sink = PricesRedisSink()
            mirror_sink = PricesAdminMirror()
            void_sink = VoidSink()

            last_wallet = None
            last_markets = None

            if task in ("wallet-assets", "all") and entry.capabilities.get("wallet_assets", False):
                c = Counter()
                try:
                    last_wallet = run_wallet_assets(
                        provider=prov, adapter=adapter, db_sink=wallet_sink, dump_raw=dump_raw, counter=c
                    )
                    c.log_json(prov, "wallet-assets")
                    ok += 1
                except Exception:
                    log.exception("WalletAssetsTask failed for %s", prov)
                _sleep_with_jitter(1)

            if task in ("prices", "all") and entry.capabilities.get("prices_spot", False):
                c = Counter()
                try:
                    run_prices(
                        provider=prov, adapter=adapter, redis_sink=prices_sink,
                        admin_mirror=mirror_sink, dump_raw=dump_raw,
                        mirror_to_admin=admin_mirror, counter=c
                    )
                    c.log_json(prov, "prices")
                    ok += 1
                except Exception:
                    log.exception("PricesTask failed for %s", prov)
                _sleep_with_jitter(1)

            if task in ("stats", "all"):
                c = Counter()
                try:
                    run_stats(
                        provider=prov, adapter=adapter,
                        wallet_items=last_wallet, market_items=last_markets,
                        dump_raw=dump_raw, counter=c
                    )
                    c.log_json(prov, "stats")
                    ok += 1
                except Exception:
                    log.exception("StatsTask failed for %s", prov)

        lock_path = _provider_lock_path(prov, base_dir)
        _with_file_lock(lock_path, worker)

    return ok

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Unified collectors runner")
    parser.add_argument("--provider", action="append", help="Provider code (repeatable). Default: all enabled")
    parser.add_argument("--task", choices=("wallet-assets", "prices", "stats", "all"), default="all")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--loop", action="store_true", help="Run forever with sleep intervals from settings")
    parser.add_argument("--dump-raw", action="store_true", help="Dump raw API responses once per day")
    parser.add_argument("--admin-mirror", action="store_true", help="Write prices mirror for admin (no history)")
    parser.add_argument("-v", "--verbose", action="count", default=0)

    args = parser.parse_args(argv or sys.argv[1:])
    _configure_logging(args.verbose)

    # Готовим Django
    _ensure_django()

    if args.once and args.loop:
        parser.error("Use either --once or --loop, not both.")

    if args.once or not args.loop:
        return 0 if run_once(
            providers=args.provider, task=args.task, dump_raw=args.dump_raw, admin_mirror=args.admin_mirror
        ) else 1

    # loop-режим: повторяем в цикле
    from . import schedules
    try:
        while True:
            rc = run_once(
                providers=args.provider, task=args.task, dump_raw=args.dump_raw, admin_mirror=args.admin_mirror
            )
            if args.task == "wallet-assets":
                time.sleep(schedules.wallet_interval_seconds())
            elif args.task == "prices":
                time.sleep(schedules.prices_interval_seconds())
            elif args.task == "stats":
                time.sleep(max(300, schedules.wallet_interval_seconds()))
            else:
                time.sleep(5)
    except KeyboardInterrupt:
        log.info("Interrupted.")
        return 0

if __name__ == "__main__":
    raise SystemExit(main())
