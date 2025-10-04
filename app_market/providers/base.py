from __future__ import annotations
from dataclasses import dataclass

from typing import Protocol

from app_market.models.exchange import Exchange


@dataclass
class AssetSyncStats:
    processed: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    disabled: int = 0


class ProviderAdapter(Protocol):
    """
    Базовый протокол адаптера провайдера (ПЛ).
    Реализации обязаны иметь .code (строка, равная LiquidityProvider.<...>)
    и метод sync_assets().
    """
    code: str

    def sync_assets(
        self,
        exchange: Exchange,
        *,
        timeout: int = 20,
        limit: int = 0,
        reconcile: bool = True,
        verbose: bool = False,
    ) -> AssetSyncStats: ...
