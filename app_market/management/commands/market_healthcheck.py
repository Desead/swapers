# app_market/management/commands/market_healthcheck.py
from __future__ import annotations
from app_market.services.health import prune_availability_logs
from typing import Iterable, Optional
from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Q

from app_market.models.exchange import Exchange, ExchangeKind, LiquidityProvider
from app_market.services.health import check_exchange, effective_modes, HealthCode


class Command(BaseCommand):
    help = (
        "Проверяет доступность поставщиков ликвидности и проставляет Exchange.is_available. "
        "CASH/PSP сейчас считаются доступными (по политике v1)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--provider",
            action="append",
            dest="providers",
            help="Фильтр по провайдерам (можно указать несколько: --provider KUCOIN --provider BYBIT).",
        )
        parser.add_argument(
            "--kind",
            action="append",
            dest="kinds",
            help="Фильтр по типам (CEX/PSP/CASH/DEX). Можно указывать несколько.",
        )
        parser.add_argument(
            "--only-home",
            action="store_true",
            dest="only_home",
            help="Проверять только провайдеров с флагом show_prices_on_home=True.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Не сохранять is_available, только печатать результат.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            dest="verbose",
            help="Подробный вывод по каждому провайдеру.",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            dest="prune",
            help="После проверки удалить историю старше retention-days (по умолчанию 7).",
        )
        parser.add_argument(
            "--retention-days",
            type=int,
            default=7,
            dest="retention_days",
            help="Сколько дней хранить историю доступности (по умолчанию 7).",
        )

    def handle(self, *args, **opts):
        providers: Optional[Iterable[str]] = opts.get("providers")
        kinds: Optional[Iterable[str]] = opts.get("kinds")
        only_home: bool = bool(opts.get("only_home"))
        dry_run: bool = bool(opts.get("dry_run"))
        verbose: bool = bool(opts.get("verbose"))

        qs = Exchange.objects.all()

        if providers:
            # Нормализуем значения по enum LiquidityProvider
            prov_values = set()
            for p in providers:
                p = (p or "").strip().upper()
                if p in LiquidityProvider.values:
                    prov_values.add(p)
                else:
                    self.stderr.write(self.style.WARNING(f"Неизвестный provider: {p} — пропускаю."))
            if prov_values:
                qs = qs.filter(provider__in=prov_values)
            else:
                self.stdout.write(self.style.WARNING("Фильтр provider задан, но ни одного валидного значения — выборка пуста."))
            if opts.get("prune"):
                days = int(opts.get("retention_days") or 7)
                removed = prune_availability_logs(days)
                self.stdout.write(self.style.SUCCESS(f"[PRUNE] retention_days={days} removed={removed}"))

        if kinds:
            kind_values = set()
            for k in kinds:
                k = (k or "").strip().upper()
                if k in ExchangeKind.values:
                    kind_values.add(k)
                else:
                    self.stderr.write(self.style.WARNING(f"Неизвестный kind: {k} — пропускаю."))
            if kind_values:
                qs = qs.filter(exchange_kind__in=kind_values)

        if only_home:
            qs = qs.filter(show_prices_on_home=True)

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("Нет провайдеров по заданным фильтрам."))
            return

        ok = 0
        changed = 0

        for ex in qs.order_by("provider"):
            prev = ex.is_available
            res = check_exchange(ex, persist=not dry_run)

            # обновим in-memory, если persist=False
            if dry_run:
                ex.is_available = res.available

            if res.available:
                ok += 1
            if res.available != prev:
                changed += 1

            if verbose:
                modes = effective_modes(ex)
                via = res.code if res.code.startswith("SKIPPED") else ("status/time" if res.code in ("OK","MAINTENANCE") else "time")
                line = (
                    f"{ex.get_provider_display():<12} "
                    f"| kind={ex.exchange_kind:<6} "
                    f"| is_avail={res.available!s:<5} ({res.code}) "
                    f"| recv={modes['can_receive_effective']!s:<5} send={modes['can_send_effective']!s:<5} "
                    f"| {res.latency_ms}ms "
                    f"| via={via}"
                )
                self.stdout.write(line)

        head = "DRY-RUN" if dry_run else "APPLIED"
        self.stdout.write(self.style.SUCCESS(f"[{head}] checked={total} ok={ok} changed={changed}"))
