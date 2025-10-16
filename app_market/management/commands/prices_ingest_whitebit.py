from __future__ import annotations
import sys
import time
import requests
from decimal import Decimal
from typing import Dict, Tuple, Set

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from app_market.models.exchange import Exchange, LiquidityProvider
from app_market.models.exchange_asset import ExchangeAsset, AssetKind
from app_market.models.prices.streaming import publish_l1_update

WB_V1_BASE = "https://whitebit.com/api/v1/public"

def _choose_quote_asset(exchange: Exchange) -> ExchangeAsset:
    """
    Выбираем «стейбл-якорь» у этого ПЛ (exchange.stablecoin).
    Если сетей несколько — берём по приоритету TRC20 > ERC20 > BEP20 > остальное.
    """
    sc = (exchange.stablecoin or "").strip().upper()
    if not sc:
        raise CommandError("У Exchange.stablecoin пусто — нужно указать стейблкоин (например, USDT или USDC).")
    qs = (ExchangeAsset.objects
          .filter(exchange=exchange, asset_code=sc)
          .order_by("id"))
    if not qs.exists():
        raise CommandError(f"У этого Exchange нет ExchangeAsset с asset_code={sc}")
    pref = ["TRC20", "ERC20", "BEP20"]
    by_chain = {ea.chain_code.upper(): ea for ea in qs}
    for c in pref:
        if c in by_chain:
            return by_chain[c]
    return qs.first()

def _wanted_bases(exchange: Exchange, stable_asset_code: str) -> Dict[int, str]:
    """
    Возвращает {base_asset_id: BASE_CODE} для всех активов этого ПЛ (кроме самого стейбла),
    ограничим криптой/фиатом — для WhiteBIT этого достаточно.
    """
    bases = (ExchangeAsset.objects
             .filter(exchange=exchange)
             .exclude(asset_code=stable_asset_code)
             .filter(asset_kind__in=[AssetKind.CRYPTO, AssetKind.FIAT])
             .only("id", "asset_code"))
    return {ea.id: ea.asset_code for ea in bases}

def _build_symbol(base_code: str, quote_code: str) -> str:
    # WhiteBIT использует формат BASE_QUOTE, напр. BTC_USDT
    return f"{base_code.upper()}_{quote_code.upper()}"

def _fetch_all_tickers() -> Dict[str, dict]:
    """
    Один запрос ко всем рынкам: /api/v1/public/tickers
    Формат ответа (сокр.):
    {
      "success": true,
      "result": {
        "BTC_USDT": { "ticker": {"bid":"..","ask":"..","last":"..", ...}, "at": 159423219 },
        ...
      }
    }
    """
    url = f"{WB_V1_BASE}/tickers"
    resp = requests.get(url, timeout=(3, 7))
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or (not data.get("success")) or ("result" not in data):
        raise RuntimeError(f"WhiteBIT /tickers unexpected response: {data!r}")
    result = data["result"]
    if not isinstance(result, dict):
        raise RuntimeError("WhiteBIT /tickers: 'result' must be a dict")
    return result

def _parse_l1(one: dict) -> Tuple[Decimal, Decimal, Decimal, int]:
    """
    one = {"ticker": {"bid":"..","ask":"..","last":"..",...}, "at": 159423219}
    Возвращает (bid, ask, last, ts_src_ms)
    """
    t = one.get("ticker") or {}
    bid = Decimal(t["bid"])
    ask = Decimal(t["ask"])
    last = Decimal(t.get("last") or t.get("last_price") or bid + (ask - bid) / 2)
    at = int(one.get("at") or 0)  # seconds
    ts_src_ms = at * 1000 if at > 0 else None
    return bid, ask, last, ts_src_ms or 0

class Command(BaseCommand):
    help = "Инжест L1 с WhiteBIT (V1 tickers) → Redis (горячий ключ + Stream). Без записи напрямую в БД."

    def add_arguments(self, parser):
        parser.add_argument("--exchange-id", type=int, help="ID Exchange с провайдером WHITEBIT (если не указан — ищем по провайдеру)")
        parser.add_argument("--loop", action="store_true", help="Крутиться в цикле (иначе один проход)")
        parser.add_argument("--sleep", type=float, default=3.0, help="Пауза между проходами в секундах (для --loop)")
        parser.add_argument("--include-cross", action="store_true", help="Публиковать также все кросс-пары из ответа, если обе монеты есть у ПЛ")
        parser.add_argument("--dry-run", action="store_true", help="Не публиковать, только показать счётчики")

    def handle(self, *args, **opts):
        ex = self._resolve_exchange(opts.get("exchange_id"))
        quote_asset = _choose_quote_asset(ex)
        quote_code = quote_asset.asset_code
        bases = _wanted_bases(ex, stable_asset_code=quote_code)
        base_symbols = {bid: _build_symbol(code, quote_code) for bid, code in bases.items()}

        self.stdout.write(self.style.NOTICE(
            f"WhiteBIT ingest for Exchange id={ex.id} (provider={ex.provider}, stable={quote_code}, base-count={len(bases)})"
        ))

        loop = bool(opts.get("loop"))
        sleep_s = float(opts.get("sleep") or 3.0)
        include_cross = bool(opts.get("include_cross"))
        dry = bool(opts.get("dry_run"))

        while True:
            pushed = 0
            skipped = 0
            cross_pushed = 0

            try:
                tickers = _fetch_all_tickers()
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"tickers error: {e}"))
                if not loop:
                    raise
                time.sleep(sleep_s)
                continue

            # 1) BASE / STABLE
            for base_id, market in base_symbols.items():
                one = tickers.get(market)
                if not one:
                    skipped += 1
                    continue
                try:
                    bid, ask, last, ts_src_ms = _parse_l1(one)
                except Exception:
                    skipped += 1
                    continue

                if not dry:
                    publish_l1_update(
                        provider_id=ex.id,
                        base_id=base_id,
                        quote_id=quote_asset.id,
                        venue_type="CEX",
                        bid=str(bid),
                        ask=str(ask),
                        last=str(last),
                        ts_src_ms=ts_src_ms,
                        src_symbol=market,
                        src_base_code=bases[base_id],
                        src_quote_code=quote_code,
                        extras={"wb_v": "v1"},
                    )
                pushed += 1

            # 2) Кроссы (по желанию)
            if include_cross:
                # Составим множество кодов монет ПЛ → id
                code_to_id: Dict[str, int] = {}
                for eid, code in bases.items():
                    code_to_id[code.upper()] = eid
                code_to_id[quote_code.upper()] = quote_asset.id  # на случай пар вида USDC_USDT

                for market, payload in tickers.items():
                    # Ожидаем формат BASE_QUOTE
                    if "_" not in market:
                        continue
                    base_code, quote_code2 = market.split("_", 1)
                    base_id2 = code_to_id.get(base_code)
                    quote_id2 = code_to_id.get(quote_code2)
                    if not base_id2 or not quote_id2:
                        continue
                    try:
                        bid, ask, last, ts_src_ms = _parse_l1(payload)
                    except Exception:
                        continue
                    if not dry:
                        publish_l1_update(
                            provider_id=ex.id,
                            base_id=base_id2,
                            quote_id=quote_id2,
                            venue_type="CEX",
                            bid=str(bid),
                            ask=str(ask),
                            last=str(last),
                            ts_src_ms=ts_src_ms,
                            src_symbol=market,
                            src_base_code=base_code,
                            src_quote_code=quote_code2,
                            extras={"wb_v": "v1", "cross": True},
                        )
                    cross_pushed += 1

            self.stdout.write(self.style.SUCCESS(
                f"Pushed: {pushed}  Skipped(no market): {skipped}" + (f"  Cross: {cross_pushed}" if include_cross else "")
            ))

            if not loop:
                break
            time.sleep(sleep_s)

    def _resolve_exchange(self, exchange_id: int | None) -> Exchange:
        if exchange_id:
            try:
                ex = Exchange.objects.get(id=exchange_id)
            except Exchange.DoesNotExist:
                raise CommandError(f"Exchange id={exchange_id} не найден.")
            if ex.provider != LiquidityProvider.WHITEBIT:
                self.stderr.write(self.style.WARNING(
                    f"Внимание: Exchange id={exchange_id} не WHITEBIT (provider={ex.provider}). Продолжаем как есть."
                ))
            return ex

        qs = Exchange.objects.filter(provider=LiquidityProvider.WHITEBIT).order_by("id")
        if not qs.exists():
            raise CommandError("В базе нет Exchange с provider=WHITEBIT.")
        if qs.count() > 1:
            self.stderr.write(self.style.WARNING(
                f"Найдено несколько WHITEBIT (ids={[e.id for e in qs]}) — беру первый."
            ))
        return qs.first()
