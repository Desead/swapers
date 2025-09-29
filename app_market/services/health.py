from __future__ import annotations

import json
import time
import typing as t
from dataclasses import dataclass
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from django.db import transaction

from app_market.models.exchange import Exchange, ExchangeKind, LiquidityProvider


# ---- Результат проверки ----

class HealthCode:
    OK = "OK"
    MAINTENANCE = "MAINTENANCE"
    NETWORK_DOWN = "NETWORK_DOWN"
    RATE_LIMIT = "RATE_LIMIT"
    AUTH_ERROR = "AUTH_ERROR"
    UNKNOWN = "UNKNOWN"
    SKIPPED_MANUAL = "SKIPPED_MANUAL"
    SKIPPED_PSP = "SKIPPED_PSP"
    SKIPPED_NO_PROBE = "SKIPPED_NO_PROBE"


@dataclass(frozen=True)
class HealthResult:
    provider: str
    exchange_id: int
    available: bool
    code: str
    detail: str = ""
    latency_ms: int = 0


# ---- Публичное API модуля ----

def check_exchange(exchange: Exchange, persist: bool = True) -> HealthResult:
    """
    Главная точка входа. Выполняет проверку и (если persist=True) проставляет Exchange.is_available.
    Твои правила:
      1) is_available — результат авто-проверки, НЕ зависит от can_receive/can_send;
      2) фактические режимы считаем как (is_available AND can_*), см. effective_modes();
      3) MANUAL: is_available всегда True;
      4) PSP: пока всегда True (хук на будущее оставлен);
      5) CEX/DEX: сначала status (если есть), потом time/ping.
    """
    # MANUAL — всегда доступен
    if exchange.provider == LiquidityProvider.MANUAL:
        res = HealthResult(exchange.provider, exchange.id, True, HealthCode.SKIPPED_MANUAL, "Manual provider; forced True.", 0)
        if persist:
            _set_availability(exchange, True)
        return res

    # PSP — пока считаем доступным; сюда потом вкрутим реальную проверку
    if exchange.exchange_kind == ExchangeKind.PSP:
        res = HealthResult(exchange.provider, exchange.id, True, HealthCode.SKIPPED_PSP, "PSP check TBD; forced True.", 0)
        if persist:
            _set_availability(exchange, True)
        return res

    if exchange.exchange_kind in {ExchangeKind.WALLET, ExchangeKind.NODE, ExchangeKind.BANK}:
        res = HealthResult(exchange.provider, exchange.id, True, HealthCode.SKIPPED_PSP, "Wallet/Node check TBD; forced True.", 0)
        if persist:
            _set_availability(exchange, True)
        return res

    # CEX/DEX и прочие
    res = _check_cex_like(exchange)
    if persist:
        _set_availability(exchange, res.available)
    return res


def effective_modes(exchange: Exchange) -> dict[str, bool]:
    """
    Возвращает фактические возможности приёма/отдачи, учитывая правило:
    режимы работают ТОЛЬКО если is_available=True.
    """
    return {
        "can_receive_effective": bool(exchange.is_available and exchange.can_receive),
        "can_send_effective": bool(exchange.is_available and exchange.can_send),
    }


# ---- Реализация проверок ----

# Публичные lightweight endpoint'ы (GET). Без ключей.
# STATUS/MAINTENANCE: публичные эндпойнты статуса (если у биржи они есть)
_CEX_STATUS_PROBES: dict[str, str] = {
    LiquidityProvider.WHITEBIT: "https://whitebit.com/api/v4/public/platform/status",
    LiquidityProvider.BYBIT: "https://api.bybit.com/v5/system/status",
    LiquidityProvider.BINANCE: "https://api.binance.com/sapi/v1/system/status",
    LiquidityProvider.OKX: "https://www.okx.com/api/v5/system/status",
    LiquidityProvider.HTX: "https://api.huobi.pro/v2/market-status",
    LiquidityProvider.BITFINEX: "https://api-pub.bitfinex.com/v2/platform/status",
    # у остальных из списка публичного maintenance-эндпойнта нет/не используем в v1
}

# TIME/PING: быстрая проверка доступности (где нет /time — лёгкий публичный GET)
_CEX_TIME_PROBES: dict[str, str] = {
    LiquidityProvider.KUCOIN: "https://api.kucoin.com/api/v1/timestamp",
    LiquidityProvider.WHITEBIT: "https://whitebit.com/api/v4/public/time",
    LiquidityProvider.MEXC: "https://api.mexc.com/api/v3/time",
    LiquidityProvider.BYBIT: "https://api.bybit.com/v5/market/time",
    LiquidityProvider.RAPIRA: "https://api.rapira.net/open/system/time",
    LiquidityProvider.BINANCE: "https://api.binance.com/api/v3/time",
    LiquidityProvider.COINBASE_EXCHANGE: "https://api.exchange.coinbase.com/time",
    LiquidityProvider.UPBIT: "https://api.upbit.com/v1/market/all",
    LiquidityProvider.BITSTAMP: "https://www.bitstamp.net/api/v2/ticker/btcusd/",
    LiquidityProvider.BINGX: "https://open-api.bingx.com/openApi/spot/v1/common/time",
    LiquidityProvider.BITFINEX: "https://api-pub.bitfinex.com/v2/ticker/tBTCUSD",
    LiquidityProvider.HTX: "https://api.huobi.pro/v1/common/timestamp",
    LiquidityProvider.GATEIO: "https://api.gateio.ws/api/v4/spot/time",
    LiquidityProvider.BITGET: "https://api.bitget.com/api/v2/public/time",
    LiquidityProvider.OKX: "https://www.okx.com/api/v5/public/time",
    LiquidityProvider.GEMINI: "https://api.gemini.com/v1/pricefeed",
    LiquidityProvider.LBANK: "https://api.lbkex.com/v2/timestamp.do",
}

_TIMEOUT_SEC = 3.0


def _check_cex_like(exchange: Exchange) -> HealthResult:
    """
    Алгоритм:
      1) Если есть status-проба и она явно говорит «maintenance» → False.
      2) Иначе делаем time/ping; если ок → True, иначе False.
      3) Если нет ни status, ни time/ping — SKIPPED_NO_PROBE (консервативно True).
    """
    # 1) STATUS
    status_url = _CEX_STATUS_PROBES.get(exchange.provider)
    if status_url:
        st = _probe_status(exchange.provider, status_url)
        if st.code == HealthCode.MAINTENANCE:
            return st
        # Если статус-страница недоступна/непонятна — не роняем, продолжаем к time/ping.

    # 2) TIME/PING
    time_url = _CEX_TIME_PROBES.get(exchange.provider)
    if time_url:
        return _probe_time(exchange.provider, time_url)

    # 3) Нет пробы
    return HealthResult(exchange.provider, exchange.id or 0, True, HealthCode.SKIPPED_NO_PROBE, "No probe configured.", 0)


def _probe_status(provider: str, url: str) -> HealthResult:
    start = time.perf_counter_ns()
    try:
        req = Request(url, method="GET", headers={"User-Agent": "swapers/healthcheck"})
        with urlopen(req, timeout=_TIMEOUT_SEC) as resp:
            latency_ms = int((time.perf_counter_ns() - start) / 1_000_000)
            status = getattr(resp, "status", 200)
            body = resp.read(4096)
            if status != 200:
                code = _http_status_to_code(status)
                return HealthResult(provider, 0, code == HealthCode.OK, code, f"HTTP {status}", latency_ms)

            data = _maybe_parse_json(body)
            # Heuristics per provider
            if provider == LiquidityProvider.WHITEBIT:
                # Ожидаем что-то вроде: {"status":1} или {"result":{"status":1}} — 1=OK, 0=maintenance
                val = _deep_get(data, ["status"], _deep_get(data, ["result", "status"], None))
                if isinstance(val, int):
                    if val == 1:
                        return HealthResult(provider, 0, True, HealthCode.OK, "status=1", latency_ms)
                    return HealthResult(provider, 0, False, HealthCode.MAINTENANCE, f"status={val}", latency_ms)
                # fallback по текстовому статусу
                text = json.dumps(data, ensure_ascii=False).lower()
                if "maintenance" in text:
                    return HealthResult(provider, 0, False, HealthCode.MAINTENANCE, "maintenance in body", latency_ms)
                return HealthResult(provider, 0, True, HealthCode.OK, "no explicit status; assuming OK", latency_ms)

            if provider == LiquidityProvider.BYBIT:
                # Ждём retCode==0 и result с "normal" (или нет признаков maintenance)
                ret_code = _deep_get(data, ["retCode"], None)
                # Поищем маркеры maintenance в теле
                text = json.dumps(data, ensure_ascii=False).lower()
                if "mainten" in text or "shutdown" in text:
                    return HealthResult(provider, 0, False, HealthCode.MAINTENANCE, "maintenance/shutdown", latency_ms)
                if ret_code == 0:
                    return HealthResult(provider, 0, True, HealthCode.OK, "retCode=0", latency_ms)
                # retCode не 0 — трактуем как UNKNOWN (не роняем, дадим шанс time/ping)
                return HealthResult(provider, 0, True, HealthCode.UNKNOWN, f"retCode={ret_code}", latency_ms)

            # Неизвестный формат — не роняем, продолжаем time/ping
            return HealthResult(provider, 0, True, HealthCode.UNKNOWN, "unparsed status; try time", latency_ms)

    except HTTPError as e:
        latency_ms = int((time.perf_counter_ns() - start) / 1_000_000)
        code = _http_status_to_code(e.code)
        # Ошибка статус-страницы не должна автоматически ронять — возвратим UNKNOWN/NETWORK и пойдём к time/ping
        return HealthResult(provider, 0, code == HealthCode.OK, code, f"HTTP {e.code}", latency_ms)
    except URLError as e:
        latency_ms = int((time.perf_counter_ns() - start) / 1_000_000)
        return HealthResult(provider, 0, True, HealthCode.UNKNOWN, f"URLError: {e.reason}", latency_ms)
    except Exception as e:
        latency_ms = int((time.perf_counter_ns() - start) / 1_000_000)
        return HealthResult(provider, 0, True, HealthCode.UNKNOWN, f"Exception: {e!r}", latency_ms)


def _probe_time(provider: str, url: str) -> HealthResult:
    start = time.perf_counter_ns()
    try:
        req = Request(url, method="GET", headers={"User-Agent": "swapers/healthcheck"})
        with urlopen(req, timeout=_TIMEOUT_SEC) as resp:
            latency_ms = int((time.perf_counter_ns() - start) / 1_000_000)
            status = getattr(resp, "status", 200)
            if status == 200:
                return HealthResult(provider, 0, True, HealthCode.OK, f"HTTP {status}", latency_ms)
            code = _http_status_to_code(status)
            return HealthResult(provider, 0, code == HealthCode.OK, code, f"HTTP {status}", latency_ms)
    except HTTPError as e:
        latency_ms = int((time.perf_counter_ns() - start) / 1_000_000)
        code = _http_status_to_code(e.code)
        return HealthResult(provider, 0, code == HealthCode.OK, code, f"HTTP {e.code}", latency_ms)
    except URLError as e:
        latency_ms = int((time.perf_counter_ns() - start) / 1_000_000)
        return HealthResult(provider, 0, False, HealthCode.NETWORK_DOWN, f"URLError: {e.reason}", latency_ms)
    except Exception as e:
        latency_ms = int((time.perf_counter_ns() - start) / 1_000_000)
        return HealthResult(provider, 0, False, HealthCode.UNKNOWN, f"Exception: {e!r}", latency_ms)


def _http_status_to_code(status: int) -> str:
    if status == 200:
        return HealthCode.OK
    if status in (401, 403):
        return HealthCode.AUTH_ERROR
    if status == 429:
        return HealthCode.RATE_LIMIT
    if 500 <= status < 600:
        return HealthCode.NETWORK_DOWN
    return HealthCode.UNKNOWN


def _maybe_parse_json(raw: bytes) -> t.Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _deep_get(obj: t.Any, path: list[str], default=None):
    cur = obj
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


@transaction.atomic
def _set_availability(exchange: Exchange, available: bool) -> None:
    """Атомарно обновляет is_available. Режимы can_* не трогаем."""
    Exchange.objects.filter(pk=exchange.pk).update(is_available=available)
