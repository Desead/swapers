from __future__ import annotations
import time
from typing import Callable, Tuple

from django.core.management.base import BaseCommand, CommandError
from app_market.models.exchange import Exchange, LiquidityProvider
from app_market.prices.price_bybit import collect_spot as bybit_collect_spot
from app_market.prices.price_whitebit import collect_spot as whitebit_collect_spot
from app_market.prices.price_kucoin import collect_spot as kucoin_collect_spot
from app_market.prices.price_mexc import collect_spot as mexc_collect_spot
from app_market.prices.price_htx import collect_spot as htx_collect_spot
from app_market.prices.price_rapira import collect_spot as rapira_collect_spot
from app_market.prices.price_twelvedata import collect_spot as twelvedata_collect_spot
from app_market.prices.price_openexchangerates import collect_spot as oer_collect_spot

CollectorFn = Callable[[Exchange, bool], Tuple[int, int]]  # (pushed, skipped)

PROVIDER_MAP: dict[str, dict[str, CollectorFn]] = {
    # provider -> category -> collector
    "bybit": {"spot": bybit_collect_spot, },
    "whitebit": {"spot": whitebit_collect_spot},
    "kucoin": {"spot": kucoin_collect_spot},
    "mexc": {"spot": mexc_collect_spot},
    "htx": {"spot": htx_collect_spot},
    "rapira": {"spot": rapira_collect_spot},
    "twelvedata": {"spot": twelvedata_collect_spot},
    "openexchangerates": {"spot": oer_collect_spot},
}

LP_ENUM_MAP: dict[str, LiquidityProvider] = {
    "bybit": LiquidityProvider.BYBIT,
    "whitebit": LiquidityProvider.WHITEBIT,
    "kucoin": LiquidityProvider.KUCOIN,
    "mexc": LiquidityProvider.MEXC,
    "htx": LiquidityProvider.HTX,
    "rapira": LiquidityProvider.RAPIRA,
    "twelvedata": LiquidityProvider.TWELVEDATA,
    "openexchangerates": LiquidityProvider.OpExRate,
}


class Command(BaseCommand):
    help = "Единый раннер: вызывает нужный сборщик цен и публикует L1 в Redis (горячий ключ + Stream)."

    def add_arguments(self, parser):
        parser.add_argument("--provider", required=True, help="например: bybit")
        parser.add_argument("--category", default="spot", help="spot (сейчас поддерживается только spot)")
        parser.add_argument("--exchange-id", type=int, help="конкретный Exchange.id (иначе возьмём первый по провайдеру)")
        parser.add_argument("--loop", action="store_true", help="крутить в цикле")
        parser.add_argument("--sleep", type=float, default=10.0, help="пауза между проходами при --loop")
        parser.add_argument("--dry-run", action="store_true", help="не публиковать, только считать")
        parser.add_argument("--dump-json-dir", dest="dump_json_dir", default=None, help="Если указан, сборщик будет сохранять сырые ответы в каталог", )

    def handle(self, *args, **opts):
        provider = (opts["provider"] or "").strip().lower()
        category = (opts["category"] or "spot").strip().lower()
        dry = bool(opts.get("dry_run"))
        loop = bool(opts.get("loop"))
        sleep_s = float(opts.get("sleep") or 3.0)

        collector = self._resolve_collector(provider, category)
        ex = self._resolve_exchange(provider, opts.get("exchange_id"))

        self.stdout.write(self.style.NOTICE(
            f"prices_ingest: provider={provider} category={category} exchange_id={ex.id} dry={dry}"
        ))

        while True:
            try:
                pushed, skipped = collector(ex, dry)
                self.stdout.write(self.style.SUCCESS(f"Pushed: {pushed}  Skipped: {skipped}"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"ingest error: {e}"))
                if not loop:
                    raise

            if not loop:
                break
            time.sleep(sleep_s)

    def _resolve_collector(self, provider: str, category: str) -> CollectorFn:
        prov = PROVIDER_MAP.get(provider)
        if not prov:
            raise CommandError(f"Провайдер не поддержан: {provider}")
        coll = prov.get(category)
        if not coll:
            raise CommandError(f"Категория '{category}' для {provider} пока не поддержана.")
        return coll

    def _resolve_exchange(self, provider: str, exchange_id: int | None) -> Exchange:
        if exchange_id:
            try:
                return Exchange.objects.get(id=exchange_id)
            except Exchange.DoesNotExist:
                raise CommandError(f"Exchange id={exchange_id} не найден.")

        lp = LP_ENUM_MAP.get(provider)
        if not lp:
            raise CommandError(f"Неизвестный провайдер: {provider}")
        qs = Exchange.objects.filter(provider=lp).order_by("id")
        if not qs.exists():
            raise CommandError(f"В базе нет Exchange с provider={lp}.")
        return qs.first()
