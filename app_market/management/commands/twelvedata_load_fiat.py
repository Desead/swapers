from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from app_market.models.exchange import Exchange, LiquidityProvider
from app_market.providers import get_adapter, has_adapter


class Command(BaseCommand):
    help = "Единоразово загрузить фиатные валюты из Twelve Data в ExchangeAsset."

    def add_arguments(self, parser):
        parser.add_argument("--exchange", type=int, help="ID Exchange с provider=TWELVEDATA (если не указан — все).")
        parser.add_argument("--timeout", type=int, default=20)
        parser.add_argument("--verbose", action="store_true", default=False)

    def handle(self, *args, **opts):
        qs = Exchange.objects.filter(provider=LiquidityProvider.TWELVEDATA)
        if opts.get("exchange") is not None:
            qs = qs.filter(id=int(opts["exchange"]))

        ex_list = list(qs)
        if not ex_list:
            raise CommandError("Нет записей Exchange с provider=TWELVEDATA")

        if not has_adapter(LiquidityProvider.TWELVEDATA):
            raise CommandError("Адаптер TWELVEDATA не зарегистрирован")

        adp = get_adapter(LiquidityProvider.TWELVEDATA)

        ok = err = 0
        for ex in ex_list:
            try:
                stats = adp.sync_assets(
                    exchange=ex,
                    timeout=int(opts["timeout"]),
                    reconcile=False,
                    verbose=bool(opts["verbose"]),
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{ex}: processed={stats.processed}, created={stats.created}, "
                        f"updated={stats.updated}, skipped={stats.skipped}, disabled={stats.disabled}"
                    )
                )
                ok += 1
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"{ex}: ошибка: {e}"))
                err += 1

        if err:
            raise CommandError(f"Завершено с ошибками: {err}/{ok + err}")
        self.stdout.write(self.style.SUCCESS(f"Готово: синк выполнен для {ok} провайдера(ов)."))
