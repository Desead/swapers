# app_market/services/stat_bybit.py
from __future__ import annotations

import hmac
import hashlib
import time
from collections import Counter
from urllib.parse import urlencode

import requests

from app_market.models import Exchange, ExchangeApiKey

BYBIT_REST = "https://api.bybit.com"


# ---------- общие утилиты ----------

def _get_keys(exchange: Exchange) -> tuple[str | None, str | None]:
    cred = ExchangeApiKey.objects.filter(exchange=exchange, is_enabled=True).only(
        "api_key", "api_secret"
    ).first()
    if not cred:
        return None, None
    return (cred.api_key or "") or None, (cred.api_secret or "") or None


def _sign_v5(secret: str, ts_ms: int, api_key: str, recv_window: int, query_str: str = "") -> str:
    """
    Подпись для Bybit v5: HMAC_SHA256(timestamp + apiKey + recvWindow + queryString).
    """
    msg = f"{ts_ms}{api_key}{recv_window}{query_str}"
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def _truthy(v) -> bool:
    s = str(v).strip().lower()
    return s in {"1", "true", "yes", "enabled", "enable", "open", "available"}


# ---------- MARKETS (public) ----------

def _fetch_exchange_info(timeout: int = 15) -> list[dict]:
    """
    GET /v5/market/instruments-info?category=spot
    Возвращает список инструментов с baseCoin/quoteCoin/status.
    """
    url = f"{BYBIT_REST}/v5/market/instruments-info"
    r = requests.get(url, params={"category": "spot"}, timeout=timeout)
    r.raise_for_status()
    data = r.json() or {}
    # ожидаем data["result"]["list"] = [...]
    result = (data.get("result") or {})
    items = result.get("list") or []
    return items


def _normalize_pairs_counts(items: list[dict]) -> dict:
    bases, quotes = set(), set()
    quote_counter: Counter[str] = Counter()
    pairs_total = 0

    for it in items or []:
        status = (it.get("status") or "").strip().lower()
        # у Bybit активный статус обычно "Trading"
        if status and status not in {"trading", "tradable", "online"}:
            continue

        base = (it.get("baseCoin") or "").strip().upper()
        quote = (it.get("quoteCoin") or "").strip().upper()
        if not base or not quote:
            # fallback из символа: "BTCUSDT" -> base/quote эвристикой в реальном коде можно не делать
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


# ---------- WALLET (private) ----------

def _signed_get_v5(path: str, *, key: str, secret: str, params: dict | None = None, timeout: int = 20):
    """
    Делает подписанный GET для Bybit v5:
      headers: X-BAPI-API-KEY, X-BAPI-TIMESTAMP, X-BAPI-RECV-WINDOW, X-BAPI-SIGN
      sign: HMAC_SHA256(timestamp + apiKey + recvWindow + queryString)
    """
    params = dict(params or {})
    recv_window = int(params.pop("recvWindow", 5000))
    qs = urlencode(sorted(params.items()), doseq=True)

    ts_ms = int(time.time() * 1000)
    sign = _sign_v5(secret, ts_ms, key, recv_window, qs)

    url = f"{BYBIT_REST}{path}"
    headers = {
        "X-BAPI-API-KEY": key,
        "X-BAPI-TIMESTAMP": str(ts_ms),
        "X-BAPI-RECV-WINDOW": str(recv_window),
        "X-BAPI-SIGN": sign,
    }
    r = requests.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _fetch_wallet_config(*, key: str, secret: str, timeout: int = 20) -> list[dict]:
    """
    GET /v5/asset/coin/query-info  (private)
    Возвращает список монет и сетей. Названия флагов у Bybit менялись — учитываем варианты.
    """
    data = _signed_get_v5("/v5/asset/coin/query-info", key=key, secret=secret, timeout=timeout)
    # ожидаем data["result"]["rows"] или data["result"]["list"] или просто список
    res = (data.get("result") or {})
    items = res.get("rows") or res.get("list") or data.get("result") or data
    return items or []


def _normalize_wallet_counts(items: list[dict]) -> dict:
    """
    Считаем:
    - уникальные монеты (coin)
    - монеты, у которых на ХОТЯ БЫ одной сети открыт ввод/вывод
    Поддерживаем разные названия флагов: depositEnable / withdrawEnable / enableDeposit / enableWithdraw / chainDeposit / chainWithdraw.
    """
    total, dep, wd = set(), set(), set()

    for it in items or []:
        sym = (it.get("coin") or it.get("name") or "").strip().upper()
        if not sym:
            continue
        total.add(sym)

        chains = it.get("chains") or it.get("networkList") or []
        for ch in chains:
            d = ch.get("depositEnable", ch.get("enableDeposit", ch.get("chainDeposit")))
            w = ch.get("withdrawEnable", ch.get("enableWithdraw", ch.get("chainWithdraw")))
            if _truthy(d):
                dep.add(sym)
            if _truthy(w):
                wd.add(sym)

    return {
        "coins_total": len(total),
        "coins_deposit_enabled": len(dep),
        "coins_withdraw_enabled": len(wd),
        "coins_list": sorted(total),
    }


# ---------- public API ----------

def collect_stats_for_exchange(exchange: Exchange, *, timeout: int = 20) -> tuple[dict, dict]:
    """
    Возвращает (wallet, markets) для Bybit.
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
    items = _fetch_exchange_info(timeout=timeout)
    markets = _normalize_pairs_counts(items)

    return wallet, markets
