from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from app_market.models.exchange import Exchange, LiquidityProvider
from app_market.providers import get_adapter, has_adapter


class Command(BaseCommand):
    help = "Единоразово загрузить наличные валюты в ExchangeAsset (Open Exchange Rates)."

    def add_arguments(self, parser):
        parser.add_argument("--exchange", type=int, help="ID Exchange с нужным provider (если не указан — все).")
        parser.add_argument("--timeout", type=int, default=20)
        parser.add_argument("--verbose", action="store_true", default=False)

    def handle(self, *args, **opts):
        # ВАЖНО: используем тот enum, который у тебя задан для OpExRate.
        # Ниже — самый вероятный вариант. Если у тебя другое имя константы,
        # просто поменяй здесь и в реестре провайдеров.
        provider_code = getattr(LiquidityProvider, "OPENEXCHANGERATES", None)
        if provider_code is None:
            # fallback: попробуем альтернативные имена
            for alt in ("OPEN_EXCHANGE_RATES", "OpExRate"):
                provider_code = getattr(LiquidityProvider, alt, None)
                if provider_code:
                    break
        if provider_code is None:
            raise CommandError("В LiquidityProvider нет константы для Open Exchange Rates (ожидались: OPENEXCHANGERATES / OPEN_EXCHANGE_RATES / OXR).")

        qs = Exchange.objects.filter(provider=provider_code)
        if opts.get("exchange") is not None:
            qs = qs.filter(id=int(opts["exchange"]))

        ex_list = list(qs)
        if not ex_list:
            raise CommandError("Нет записей Exchange с выбранным провайдером Open Exchange Rates")

        if not has_adapter(provider_code):
            raise CommandError("Адаптер Open Exchange Rates не зарегистрирован в providers.registry")

        adp = get_adapter(provider_code)

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
