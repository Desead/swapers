from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ProviderMeta:
    provider: str
    exchange_kind: Optional[str] = None  # spot, psp, cash, etc (из ваших enum)
    rate_limit: Optional[str] = None
    env: Optional[str] = None  # dev|prod
    enabled: bool = True


@dataclass(frozen=True)
class WalletAssetDTO:
    asset: str
    network: Optional[str]
    in_enabled: bool
    out_enabled: bool
    min_deposit: Optional[str] = None
    min_withdraw: Optional[str] = None
    withdraw_fee: Optional[str] = None
    is_fiat: bool = False
    is_stable: bool = False
    native_codes: Dict[str, Any] = field(default_factory=dict)
    ts_source: Optional[datetime] = None


@dataclass(frozen=True)
class MarketPairDTO:
    base: str
    quote: str
    provider_symbol: Optional[str] = None
    status: str = "active"  # active|halted|postonly...
    ts_source: Optional[datetime] = None


@dataclass(frozen=True)
class L1PriceDTO:
    base: str
    quote: str
    last: str
    provider_symbol: Optional[str] = None
    ts_price: Optional[datetime] = None
    latency_ms: Optional[int] = None
    source_note: Optional[str] = None  # REST/WSS/batch


@dataclass
class StatsSnapshot:
    wallet_coins: int
    market_coins: int
    coverage_pct: float
    top_quotes: List[str]
    deltas_inout: Dict[str, int]
    as_of: datetime
    notes: Optional[str] = None


# Удобные типы
RawPayload = Any  # что угодно, что вернул API (dict|list|str...)
CapabilityResult = Tuple[Sequence[Any], Optional[RawPayload]]  # (нормализовано, сырой дамп|None)
