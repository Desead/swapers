from __future__ import annotations
import os, json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Tuple, Optional

import requests

from app_market.models.exchange import Exchange
from app_market.models.account import ExchangeApiKey
from app_market.prices.publisher import publish_l1_code

API_BASE = "https://openexchangerates.org/api"
LATEST_URL = f"{API_BASE}/latest.json"


def _get_api_key_from_db(ex: Exchange) -> str:
    rec = (
        ExchangeApiKey.objects
        .filter(exchange=ex, is_enabled=True)
        .order_by("id")
        .only("api_key")
        .first()
    )
    if not rec or not (rec.api_key or "").strip():
        raise RuntimeError(f"{ex}: не найден активный API-ключ OpenExchangeRates в ExchangeApiKey")
    return rec.api_key.strip()


def _dump_json_once(payload, directory: Optional[str], filename: str) -> None:
    """Сохранить JSON один раз: если файл уже есть — ничего не делаем."""
    if not directory:
        return
    try:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, filename)
        if os.path.exists(path):
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # дамп — вспомогательный, не мешаем основному потоку


def collect_spot(ex: Exchange, dry_run: bool = False, dump_json_dir: Optional[str] = None) -> Tuple[int, int]:
    """
    OpenExchangeRates: забираем ВСЕ курсы из /latest.json и публикуем только BASE/QUOTE.
    • base берём из payload["base"] (на free-плане это USD).
    • bid/ask = rate (синтетика), extras['synthetic_bbo']=True.
    • если указан dump_json_dir — кладём сырой latest.json как oer_latest.json (однократно).
    """
    app_id = _get_api_key_from_db(ex)

    r = requests.get(LATEST_URL, params={"app_id": app_id}, headers={"Accept": "application/json"}, timeout=(8, 20))
    r.raise_for_status()
    payload = r.json()

    # дамп один раз
    _dump_json_once(payload, dump_json_dir, "oer_latest.json")

    if not isinstance(payload, dict) or not isinstance(payload.get("rates"), dict):
        return 0, 0

    rates: dict = payload["rates"]
    base_ccy: str = str(payload.get("base") or "USD").upper()
    ts_src_ms: Optional[int] = None
    try:
        ts_val = payload.get("timestamp")
        if ts_val is not None:
            ts_src_ms = int(ts_val) * 1000
    except Exception:
        ts_src_ms = None

    pushed = skipped = 0
    exchange_kind = ex.exchange_kind

    for ccy, val in rates.items():
        quote = str(ccy).upper()
        if quote == base_ccy:
            continue
        try:
            px = Decimal(str(val))
        except (InvalidOperation, TypeError):
            skipped += 1
            continue
        if px <= 0:
            skipped += 1
            continue

        if not dry_run:
            publish_l1_code(
                provider_id=ex.id,
                exchange_kind=exchange_kind,
                base_code=base_ccy,
                quote_code=quote,
                bid=px,    # синтетический BBO
                ask=px,
                last=px,
                ts_src_ms=ts_src_ms,
                src_symbol=f"{base_ccy}/{quote}",
                extras={"oer_base": base_ccy, "synthetic_bbo": True, "synthetic_from": "oer_latest"},
            )
        pushed += 1

    return pushed, skipped
