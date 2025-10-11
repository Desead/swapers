from __future__ import annotations

from typing import Iterable, Optional

from django.core.management.base import BaseCommand, CommandError

from app_market.models.exchange import Exchange, ExchangeKind
from app_market.providers import get_adapter, has_adapter, list_adapters


class Command(BaseCommand):
    help = (
        "Синхронизация активов (монета+сеть) у провайдеров ликвидности.\n"
        "Работает через адаптеры из app_market.providers.*. Для неподдерживаемых ПЛ — пропускает."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider",
            default="ALL",
            help="Код провайдера (LiquidityProvider.*) или ALL. Пример: WHITEBIT",
        )
        parser.add_argument(
            "--exchange-id",
            type=int,
            help="ID конкретного Exchange (если нужно ограничить)."
        )
        parser.add_argument("--timeout", type=int, default=20, help="HTTP таймаут, сек")
        parser.add_argument("--limit", type=int, default=0, help="Ограничить кол-во записей для отладки")
        parser.add_argument("--no-reconcile", action="store_true", help="Не гасить AD/AW у отсутствующих")
        parser.add_argument("--verbose", action="store_true", help="Подробный вывод")

    def _iter_targets(self, provider: str, exchange_id: Optional[int]) -> Iterable[Exchange]:
        """
        Возвращает генератор Exchange для синхронизации.
        Правила:
          - ориентируемся только на is_available=True;
          - ExchangeKind.MANUAL/OFFICE разрешены, но реальный запуск будет только если есть адаптер;
          - Если provider=ALL — обрабатываем все is_available=True.
          - Если указан exchange_id — берём ровно один (даже если is_available=False), это «ручной» запуск.
        """
        if exchange_id:
            try:
                ex = Exchange.objects.get(pk=exchange_id)
            except Exchange.DoesNotExist:
                raise CommandError(f"Exchange id={exchange_id} не найден")
            yield ex
            return

        if provider and provider != "ALL":
            qs = Exchange.objects.filter(provider=provider)
        else:
            qs = Exchange.objects.filter(is_available=True)

        for ex in qs.order_by("provider"):
            yield ex

    def handle(self, *args, **opts):
        provider = (opts["provider"] or "ALL").strip().upper()
        exchange_id = opts.get("exchange_id")
        timeout = int(opts["timeout"] or 20)
        limit = int(opts["limit"] or 0)
        reconcile = not bool(opts.get("no_reconcile"))
        verbose = bool(opts.get("verbose"))

        processed_any = False
        for ex in self._iter_targets(provider, exchange_id):
            processed_any = True
            code = ex.provider

            # MANUAL/OFFICE — пропуск
            if ex.exchange_kind in {ExchangeKind.MANUAL, ExchangeKind.OFFICE}:
                if verbose:
                    self.stdout.write(self.style.WARNING(f"→ {code} (id={ex.id}) пропущен: MANUAL/OFFICE"))
                continue

            if not has_adapter(code):
                if verbose:
                    self.stdout.write(self.style.WARNING(f"→ {code} (id={ex.id}) пропущен: нет адаптера"))
                continue

            adapter = get_adapter(code)
            assert adapter is not None

            if verbose:
                self.stdout.write(f"→ {code} (id={ex.id})")

            try:
                stats = adapter.sync_assets(
                    ex,
                    timeout=timeout,
                    limit=limit,
                    reconcile=reconcile,
                    verbose=verbose,
                )
            except Exception as e:
                # Не роняем весь процесс — просто сообщаем и идём дальше
                self.stderr.write(self.style.ERROR(f"{code}: ошибка синхронизации: {e}"))
                continue

            msg = (
                f"{code} done: processed={stats.processed}, "
                f"created={stats.created}, updated={stats.updated}, skipped={stats.skipped}"
            )
            if reconcile:
                msg += f", disabled_by_reconcile={stats.disabled}"
            self.stdout.write(self.style.SUCCESS(msg))

        if not processed_any:
            # Подсказка: какие вообще адаптеры есть
            adapters = ", ".join(list_adapters()) or "нет"
            raise CommandError(f"Нечего синхронизировать. Доступные адаптеры: {adapters}")
