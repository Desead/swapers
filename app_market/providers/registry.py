from __future__ import annotations
from typing import Dict, Type, Optional

from app_market.models.exchange import LiquidityProvider
from .base import ProviderAdapter
from app_market.providers.cex.whitebit import WhitebitAdapter
from app_market.providers.cex.kucoin import KucoinAdapter
from app_market.providers.cex.bybit import BybitAdapter
from app_market.providers.cex.htx import HtxAdapter
from app_market.providers.cex.mexc import MexcAdapter

_REGISTRY: Dict[str, Type[ProviderAdapter]] = {
    LiquidityProvider.WHITEBIT: WhitebitAdapter,
    LiquidityProvider.KUCOIN: KucoinAdapter,
    LiquidityProvider.BYBIT: BybitAdapter,
    LiquidityProvider.HTX: HtxAdapter,
    LiquidityProvider.MEXC: MexcAdapter,
}


def has_adapter(provider_code: str) -> bool:
    return provider_code in _REGISTRY


def get_adapter(provider_code: str) -> Optional[ProviderAdapter]:
    cls = _REGISTRY.get(provider_code)
    return cls() if cls else None


def list_adapters() -> list[str]:
    return sorted(_REGISTRY.keys())
