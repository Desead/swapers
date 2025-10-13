from __future__ import annotations

from typing import Any, Iterable, Optional
from decimal import Decimal

from django.db import transaction, models

from app_market.providers.base import UnifiedProviderBase, ProviderRow, AssetSyncStats
from app_market.providers.numeric import U, D
from app_market.models import ExchangeAsset, ExchangeApiKey
from app_market.models.exchange_asset import AssetKind

_ALL_FIAT = [
    {"asset_code": "USD", "asset_name": "US Dollar", "amount_precision": 2},
    {"asset_code": "RUB", "asset_name": "Russian Ruble", "amount_precision": 2},
    {"asset_code": "EUR", "asset_name": "Euro", "amount_precision": 2},
    {"asset_code": "UAH", "asset_name": "Ukrainian Hryvnia", "amount_precision": 2},
    {"asset_code": "BYN", "asset_name": "Belarusian Ruble", "amount_precision": 2},
    {"asset_code": "KZT", "asset_name": "Kazakhstani Tenge", "amount_precision": 2},
    {"asset_code": "GBP", "asset_name": "British Pound", "amount_precision": 2},
    {"asset_code": "AED", "asset_name": "UAE Dirham", "amount_precision": 2},
    {"asset_code": "TRY", "asset_name": "Turkish Lira", "amount_precision": 2},
    {"asset_code": "COP", "asset_name": "Colombian Peso", "amount_precision": 2},
    {"asset_code": "PLN", "asset_name": "Polish Zloty", "amount_precision": 2},
    {"asset_code": "ILS", "asset_name": "Israeli New Shekel", "amount_precision": 2},
    {"asset_code": "CZK", "asset_name": "Czech Koruna", "amount_precision": 2},
    {"asset_code": "GEL", "asset_name": "Georgian Lari", "amount_precision": 2},
    {"asset_code": "AMD", "asset_name": "Armenian Dram", "amount_precision": 2},
    {"asset_code": "CAD", "asset_name": "Canadian Dollar", "amount_precision": 2},
    {"asset_code": "THB", "asset_name": "Thai Baht", "amount_precision": 2},
    {"asset_code": "AUD", "asset_name": "Australian Dollar", "amount_precision": 2},
    {"asset_code": "NGN", "asset_name": "Nigerian Naira", "amount_precision": 2},
    {"asset_code": "BGN", "asset_name": "Bulgarian Lev", "amount_precision": 2},
    {"asset_code": "AZN", "asset_name": "Azerbaijani Manat", "amount_precision": 2},
    {"asset_code": "MDL", "asset_name": "Moldovan Leu", "amount_precision": 2},
    {"asset_code": "CHF", "asset_name": "Swiss Franc", "amount_precision": 2},
    {"asset_code": "RON", "asset_name": "Romanian Leu", "amount_precision": 2},
    {"asset_code": "IDR", "asset_name": "Indonesian Rupiah", "amount_precision": 0},
    {"asset_code": "CNY", "asset_name": "Chinese Yuan", "amount_precision": 2},
    {"asset_code": "MXN", "asset_name": "Mexican Peso", "amount_precision": 2},
    {"asset_code": "SGD", "asset_name": "Singapore Dollar", "amount_precision": 2},
    {"asset_code": "KRW", "asset_name": "South Korean Won", "amount_precision": 0},
    {"asset_code": "BRL", "asset_name": "Brazilian Real", "amount_precision": 2},
    {"asset_code": "INR", "asset_name": "Indian Rupee", "amount_precision": 2},
    {"asset_code": "JPY", "asset_name": "Japanese Yen", "amount_precision": 0},
    {"asset_code": "ARS", "asset_name": "Argentine Peso", "amount_precision": 2},
    {"asset_code": "KGS", "asset_name": "Kyrgyzstani Som", "amount_precision": 2},
    {"asset_code": "EGP", "asset_name": "Egyptian Pound", "amount_precision": 2},
    {"asset_code": "VND", "asset_name": "Vietnamese Dong", "amount_precision": 0},
]


class OpenExchangeRatesCashAdapter(UnifiedProviderBase):
    """
    CASH-провайдер (инициализация наличных валют) для Open Exchange Rates.

    Поведение:
    - Один раз: если у exchange уже есть активы — пропуск.
    - Источник списка — фиксированный (_ALL_FIAT).
    - AD/AW=True, amount_precision из списка, nominal=1.
    - «Мин. ввод (в USDT)» = 1000 → пишем в deposit_min_usdt.
    - Остальные числовые поля = 0.
    - asset_kind = CASH (явно проставляем после записи).
    """

    code = "OPENEXCHANGERATES"

    def fetch_payload(self, *, timeout: int) -> Any:
        return list(_ALL_FIAT)

    def iter_rows(self, payload: Any) -> Iterable[ProviderRow]:
        for it in (payload or []):
            code = U(it.get("asset_code") or "")
            if not code:
                continue
            name = (it.get("asset_name") or code).strip()
            prec = int(it.get("amount_precision") or 2)

            yield ProviderRow(
                asset_code=code,
                asset_name=name,

                # пустая сеть ⇒ базовый пайплайн не включает крипто-гард
                chain_code="",
                chain_name="",

                AD=True,
                AW=True,

                conf_dep=0,
                conf_wd=0,

                # обычные лимиты — нули (наличные)
                dep_min=D(0),
                dep_max=D(0),
                wd_min=D(0),
                wd_max=D(0),

                dep_fee_pct=D(0),
                dep_fee_fix=D(0),
                wd_fee_pct=D(0),
                wd_fee_fix=D(0),

                requires_memo=False,
                amount_precision=prec,
                is_stable=False,

                raw_meta={"source": "openexchangerates/static_cash"},
            )

    def policy_write_withdraw_max(self) -> bool:
        return True

    def provider_name_for_status(self) -> str:
        return "OPENEXCHANGERATES"

    def _get_api_key(self, exchange) -> Optional[str]:
        return (
            ExchangeApiKey.objects
            .filter(exchange=exchange, is_enabled=True)
            .values_list("api_key", flat=True)
            .first()
        )

    def sync_assets(
            self,
            exchange,
            *,
            timeout: int = 20,
            limit: int = 0,
            reconcile: bool = False,
            verbose: bool = False,
    ) -> AssetSyncStats:
        # Если уже есть записи по этому exchange — ничего не делаем
        if ExchangeAsset.objects.filter(exchange=exchange).exists():
            if verbose:
                print(f"[{self.code}] уже инициализировано → пропуск")
            return AssetSyncStats()

        _ = self._get_api_key(exchange)  # на будущее

        # Первая заливка
        stats = super().sync_assets(exchange, timeout=timeout, limit=limit, reconcile=False, verbose=verbose)

        # После записи — проставим CASH и min в USDT = 1000
        with transaction.atomic():
            (ExchangeAsset.objects
            .filter(exchange=exchange)
            .update(
                asset_kind=AssetKind.CASH,
                nominal=1,
                deposit_min_usdt=Decimal("1000"),
                withdraw_min_usdt=Decimal("1000"),
                amount_precision_display=2,
            )
            )

        return stats
