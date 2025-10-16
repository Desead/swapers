# app_market/services/stat_mexc.py
from __future__ import annotations

import hmac
import hashlib
import time
from urllib.parse import urlencode
from collections import Counter
import requests

from app_market.models import Exchange, ExchangeApiKey

MEXC_REST = "https://api.mexc.com"


def _get_keys(exchange: Exchange) -> tuple[str | None, str | None]:
    cred = ExchangeApiKey.objects.filter(exchange=exchange, is_enabled=True).only(
        "api_key", "api_secret"
    ).first()
    if not cred:
        return None, None
    return (cred.api_key or "") or None, (cred.api_secret or "") or None


def _server_time(timeout: int = 10) -> int:
    r = requests.get(f"{MEXC_REST}/api/v3/time", timeout=timeout)
    r.raise_for_status()
    data = r.json() or {}
    return int(data.get("serverTime") or int(time.time() * 1000))


def _signed_get(path: str, *, key: str, secret: str, params: dict | None = None, timeout: int = 20):
    params = dict(params or {})
    params.setdefault("timestamp", _server_time(timeout=timeout))
    params.setdefault("recvWindow", 5000)

    qs = urlencode(params)
    sig = hmac.new(secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{MEXC_REST}{path}?{qs}&signature={sig}"
    headers = {"X-MEXC-APIKEY": key}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _fetch_exchange_info(timeout: int = 15) -> list[dict]:
    url = f"{MEXC_REST}/api/v3/exchangeInfo"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "symbols" in data:
        return data["symbols"] or []
    return data or []


def _fetch_wallet_config(*, key: str, secret: str, timeout: int = 20) -> list[dict]:
    return _signed_get("/api/v3/capital/config/getall", key=key, secret=secret, timeout=timeout)


def _normalize_wallet_counts(items: list[dict]) -> dict:
    total, dep, wd = set(), set(), set()
    for it in items or []:
        sym = (it.get("coin") or "").strip().upper()
        if not sym:
            continue
        total.add(sym)
        for net in (it.get("networkList") or []):
            if net.get("depositEnable") is True:
                dep.add(sym)
            if net.get("withdrawEnable") is True:
                wd.add(sym)
    return {
        "coins_total": len(total),
        "coins_deposit_enabled": len(dep),
        "coins_withdraw_enabled": len(wd),
        "coins_list": sorted(total),
    }


def _normalize_pairs_counts(symbols: list[dict]) -> dict:
    bases, quotes = set(), set()
    quote_counter: Counter[str] = Counter()
    pairs_total = 0

    for s in symbols or []:
        status = str(s.get("status", "1")).strip()
        if status not in {"1", "ONLINE", "online", "Online"}:
            continue
        if s.get("isSpotTradingAllowed") is False:
            continue

        base = (s.get("baseAsset") or "").strip().upper()
        quote = (s.get("quoteAsset") or "").strip().upper()
        if not base or not quote:
            continue

        bases.add(base)
        quotes.add(quote)
        quote_counter[quote] += 1
        pairs_total += 1

    coins_trade = sorted(bases | quotes)
    quote_popularity = [{"quote": q, "pairs": c} for q, c in quote_counter.most_common()]
    return {
        "pairs_total": pairs_total,
        "coins_trade_total": len(coins_trade),
        "base_coins_total": len(bases),
        "quote_coins_total": len(quotes),
        "quote_popularity": quote_popularity,
        "top_quote": quote_popularity[0]["quote"] if quote_popularity else None,
    }


def collect_stats_for_exchange(exchange: Exchange, *, timeout: int = 20) -> tuple[dict, dict]:
    """
    Возвращает (wallet, markets) без изменения объекта Exchange.
    Кошелёк — приватный эндпоинт (нужны ключи), маркет — публичный.
    """
    # WALLET
    wallet = {"coins_total": 0, "coins_deposit_enabled": 0, "coins_withdraw_enabled": 0, "coins_list": []}
    k, s = _get_keys(exchange)
    if not (k and s):
        wallet["error"] = "missing_api_keys"
    else:
        try:
            wallet_raw = _fetch_wallet_config(key=k, secret=s, timeout=timeout)
            wallet = _normalize_wallet_counts(wallet_raw)
        except requests.HTTPError as e:
            wallet["error"] = f"http_{e.response.status_code}"
        except Exception as e:
            wallet["error"] = f"unexpected:{e.__class__.__name__}"

    # MARKETS
    symbols = _fetch_exchange_info(timeout=timeout)
    markets = _normalize_pairs_counts(symbols)

    return wallet, markets
