# app_market/tests/collectors/_dummies.py
from __future__ import annotations
from dataclasses import dataclass

# Фейковый адаптер для wallet-assets
@dataclass
class DummyStats:
    processed: int = 3
    created: int = 2
    updated: int = 1
    skipped: int = 0
    disabled: int = 0

class DummyAdapter:
    def __init__(self, credentials=None):
        self.credentials = credentials

    # повторяет сигнатуру твоих адаптеров
    def sync_assets(self, *, exchange, timeout=20, limit=0, reconcile=True, verbose=False):
        assert exchange is not None
        return DummyStats()

# Фейковый коллектор цен — имитирует publish в Redis и возвращает (pushed, skipped)
def dummy_collect_spot(exchange, dry_run=False):
    # симулируем 1 публикацию — это подхватится «зеркалом» в БД
    from app_market.prices.publisher import publish_l1_code
    publish_l1_code(
        provider_id=exchange.id, exchange_kind=str(exchange.exchange_kind),
        base_code="BTC", quote_code="USDT",
        bid="100.0", ask="101.0", last="100.5",
        ts_src_ms=None, src_symbol="BTCUSDT", extras={"src": "dummy"},
    )
    return 1, 0
