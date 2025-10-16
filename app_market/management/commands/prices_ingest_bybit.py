from __future__ import annotations
import time
import requests
from decimal import Decimal
from typing import Dict, Tuple

from django.core.management.base import BaseCommand, CommandError

from app_market.models.exchange import Exchange, LiquidityProvider
from app_market.models.exchange_asset import ExchangeAsset, AssetKind
from app_market.models.prices.streaming import publish_l1_update

BYBIT_BASE = "https://api.bybit.com"

def _choose_quote_asset(exchange: Exchange) -> ExchangeAsset:
    """
    Выбираем quote-актив (стейбл) для ПЛ:
    - поддерживаем список в Exchange.stablecoin: 'USDT,USDC' или через пробелы
    - если ничего не указано/не найдено — берём любой is_stablecoin=True у этого ПЛ
    - приоритет по сетям: TRC20 > ERC20 > BEP20 > остальное
    """
    pref_chains = ["TRC20", "ERC20", "BEP20"]

    # 1) кандидаты из поля exchange.stablecoin
    raw = (exchange.stablecoin or "").upper()
    codes = [c for c in (raw.replace("|", " ").replace(",", " ").split()) if c]
    # дефолтный набор — вдруг поле пустое или там экзотика
    if not codes:
        codes = ["USDT", "USDC"]

    qs = (ExchangeAsset.objects
          .filter(exchange=exchange, asset_code__in=codes)
          .only("id", "asset_code", "chain_code", "is_stablecoin")
          .order_by("id"))
    if qs.exists():
        # сначала предпочитаем записи с is_stablecoin=True
        stables = [ea for ea in qs if ea.is_stablecoin]
        pool = stables or list(qs)
        by_chain = { (ea.chain_code or "").upper(): ea for ea in pool }
        for c in pref_chains:
            if c in by_chain:
                return by_chain[c]
        return pool[0]

    # 2) fallback: любой стейбл у этого ПЛ
    qs2 = (ExchangeAsset.objects
           .filter(exchange=exchange, is_stablecoin=True)
           .only("id", "asset_code", "chain_code")
           .order_by("id"))
    if qs2.exists():
        by_chain = { (ea.chain_code or "").upper(): ea for ea in qs2 }
        for c in pref_chains:
            if c in by_chain:
                return by_chain[c]
        return qs2.first()

    # 3) ничего не нашли — собираем диагностику
    have_codes = list(
        ExchangeAsset.objects.filter(exchange=exchange)
        .values_list("asset_code", flat=True).distinct()
    )
    raise CommandError(
        f"Не найден quote-актив для {exchange.provider}. "
        f"Exchange.stablecoin={exchange.stablecoin!r}. "
        f"Доступные asset_code у этого ПЛ: {sorted(set(have_codes))}"
    )

def _wanted_bases(exchange: Exchange, stable_asset_code: str) -> Dict[int, str]:
    """
    Возвращает {id: BASE_CODE} для всех активов ПЛ, которые НЕ стейблы.
    Исключаем:
      - asset_code == текущему quote-коду (например, USDT)
      - все is_stablecoin=True (например, USDC), чтобы они не попадали в BASE
    """
    bases = (ExchangeAsset.objects
             .filter(exchange=exchange)
             .exclude(asset_code=stable_asset_code)
             .exclude(is_stablecoin=True)
             .filter(asset_kind__in=[AssetKind.CRYPTO, AssetKind.FIAT])
             .only("id", "asset_code"))
    return {ea.id: ea.asset_code for ea in bases}

def _fetch_all_spot_tickers() -> Dict[str, dict]:
    """
    GET /v5/market/tickers?category=spot
    Ответ:
    {
      "retCode":0,"retMsg":"OK",
      "result":{"category":"spot","list":[
        {"symbol":"BTCUSDT","bid1Price":"...","ask1Price":"...","lastPrice":"...","time":"1699999999999", ...},
        ...
      ]},
      "time": 1699999999999
    }
    """
    url = f"{BYBIT_BASE}/v5/market/tickers"
    resp = requests.get(url, params={"category": "spot"}, timeout=(3, 7))
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or data.get("retCode") != 0:
        raise RuntimeError(f"Bybit /v5/market/tickers unexpected: {data!r}")
    result = data.get("result") or {}
    items = result.get("list") or []
    # вернём словарь {symbol: item}
    return {item.get("symbol"): item for item in items if isinstance(item, dict) and item.get("symbol")}

def _parse_l1(one: dict) -> Tuple[Decimal, Decimal, Decimal, int]:
    bid = Decimal(one["bid1Price"])
    ask = Decimal(one["ask1Price"])
    last = Decimal(one.get("lastPrice") or (bid + (ask - bid) / 2))
    ts_ms = int(one.get("time") or 0)
    return bid, ask, last, (ts_ms if ts_ms > 0 else 0)

class Command(BaseCommand):
    help = "Инжест L1 с Bybit (v5 spot tickers) → Redis (горячий ключ + Stream). Без записи напрямую в БД."

    def add_arguments(self, parser):
        parser.add_argument("--exchange-id", type=int, help="ID Exchange провайдера BYBIT (если не указан — берём первый BYBIT)")
        parser.add_argument("--loop", action="store_true", help="Крутиться в цикле (иначе один проход)")
        parser.add_argument("--sleep", type=float, default=3.0, help="Пауза между проходами в секундах (для --loop)")
        parser.add_argument("--include-cross", action="store_true", help="Публиковать также все кроссы из ответа, если обе монеты есть у ПЛ")
        parser.add_argument("--dry-run", action="store_true", help="Не публиковать, только посчитать")

    def handle(self, *args, **opts):
        ex = self._resolve_exchange(opts.get("exchange_id"))
        quote_asset = _choose_quote_asset(ex)
        quote_code = quote_asset.asset_code.upper()
        bases = _wanted_bases(ex, stable_asset_code=quote_code)

        self.stdout.write(self.style.NOTICE(
            f"Bybit ingest for Exchange id={ex.id} (provider={ex.provider}, stable={quote_code}, base-count={len(bases)})"
        ))

        loop = bool(opts.get("loop"))
        sleep_s = float(opts.get("sleep") or 3.0)
        include_cross = bool(opts.get("include_cross"))
        dry = bool(opts.get("dry_run"))

        # словарь для проверки кроссов: код монеты → id
        code_to_id = {code.upper(): eid for eid, code in bases.items()}
        code_to_id[quote_code] = quote_asset.id

        while True:
            pushed = 0
            skipped = 0
            cross_pushed = 0

            try:
                tickers = _fetch_all_spot_tickers()
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"tickers error: {e}"))
                if not loop:
                    raise
                time.sleep(sleep_s)
                continue

            # 1) BASE/STABLE
            for base_id, base_code in bases.items():
                symbol = f"{base_code.upper()}{quote_code}"  # Bybit spot без подчёркивания: BTCUSDT
                one = tickers.get(symbol)
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
                        ts_src_ms=ts_src_ms or None,
                        src_symbol=symbol,
                        src_base_code=base_code,
                        src_quote_code=quote_code,
                        extras={"bybit_v": "v5"},
                    )
                pushed += 1

            # 2) Кроссы (по желанию)
            if include_cross:
                # Попробуем разобрать символ как BASE+QUOTE по известным кодам
                for symbol, payload in tickers.items():
                    sym = (symbol or "").upper()
                    # переберём возможные QUOTE-коды (из code_to_id), ищем суффикс
                    matched = False
                    for q_code, q_id in code_to_id.items():
                        if not sym.endswith(q_code):
                            continue
                        b_code = sym[:-len(q_code)]
                        b_id = code_to_id.get(b_code)
                        if not b_id or b_id == q_id:
                            continue
                        try:
                            bid, ask, last, ts_src_ms = _parse_l1(payload)
                        except Exception:
                            continue
                        if not dry:
                            publish_l1_update(
                                provider_id=ex.id,
                                base_id=b_id,
                                quote_id=q_id,
                                venue_type="CEX",
                                bid=str(bid),
                                ask=str(ask),
                                last=str(last),
                                ts_src_ms=ts_src_ms or None,
                                src_symbol=symbol,
                                src_base_code=b_code,
                                src_quote_code=q_code,
                                extras={"bybit_v": "v5", "cross": True},
                            )
                        cross_pushed += 1
                        matched = True
                        break
                    if matched:
                        continue

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
            if ex.provider != LiquidityProvider.BYBIT:
                self.stderr.write(self.style.WARNING(
                    f"Внимание: Exchange id={exchange_id} не BYBIT (provider={ex.provider}). Продолжаю как есть."
                ))
            return ex

        qs = Exchange.objects.filter(provider=LiquidityProvider.BYBIT).order_by("id")
        if not qs.exists():
            raise CommandError("В базе нет Exchange с provider=BYBIT.")
        if qs.count() > 1:
            self.stderr.write(self.style.WARNING(
                f"Найдено несколько BYBIT (ids={[e.id for e in qs]}) — беру первый."
            ))
        return qs.first()
