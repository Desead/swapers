from __future__ import annotations
from typing import Dict, Type, Optional

from app_market.models.exchange import LiquidityProvider
from app_market.providers.cex.whitebit import WhitebitAdapter
from app_market.providers.cex.kucoin import KucoinAdapter
from app_market.providers.cex.bybit import BybitAdapter
from app_market.providers.cex.htx import HtxAdapter
from app_market.providers.cex.mexc import MexcAdapter
from app_market.providers.cex.rapira import RapiraAdapter
from app_market.providers.cash.twelvedata import TwelveDataCashAdapter
from app_market.providers.cash.openexchangerates import OpenExchangeRatesCashAdapter

# Единый реестр "код провайдера" -> класс адаптера
_REGISTRY: Dict[str, Type] = {
    LiquidityProvider.WHITEBIT: WhitebitAdapter,
    LiquidityProvider.KUCOIN: KucoinAdapter,
    LiquidityProvider.BYBIT: BybitAdapter,
    LiquidityProvider.HTX: HtxAdapter,
    LiquidityProvider.MEXC: MexcAdapter,
    LiquidityProvider.RAPIRA: RapiraAdapter,
    # Наличные / справочники:
    LiquidityProvider.TWELVEDATA: TwelveDataCashAdapter,
    LiquidityProvider.OpExRate: OpenExchangeRatesCashAdapter,
}

def has_adapter(provider_code: str) -> bool:
    return provider_code in _REGISTRY

def get_adapter(provider_code: str):
    cls = _REGISTRY.get(provider_code)
    return cls() if cls else None

def list_adapters() -> list[str]:
    return sorted(_REGISTRY.keys())
