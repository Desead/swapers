from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP, getcontext
from typing import Any, Optional, Set

from django.conf import settings

from app_main.models import SiteSetup
from app_market.models.exchange_asset import AssetKind
from app_market.models.account import ExchangeApiKey


# =========================
# Global Decimal context
# =========================
getcontext().prec = int(getattr(settings, "DECIMAL_CONTEXT_PREC", 50))


# =========================
# What this module exports
# =========================
__all__ = [
    # Identity / misc
    "UA",

    # DB geometry
    "DB_INT_DIGITS", "DB_DEC_PLACES", "DB_QUANT",
    "DB_MAX_AMOUNT", "DB_MAX_AMOUNT_SAFE",

    # Calculation geometry
    "CALC_INT_DIGITS", "CALC_DEC_PLACES", "CALC_QUANT",
    "CALC_MAX_AMOUNT",

    # Percents
    "PERCENT_PLACES_DB", "PERCENT_PLACES_CALC",
    "PERCENT_QUANT_DB", "PERCENT_QUANT_CALC",
    "MAX_PERCENT",

    # Crypto withdraw business limits (for CRYPTO assets)
    "CRYPTO_WD_MIN_MIN", "CRYPTO_WD_MIN_MAX", "CRYPTO_WD_FEE_FIX_MAX",
    "crypto_withdraw_guard",

    # Core numeric utils
    "D",
    "to_calc_amount", "to_db_amount",
    "to_calc_percent", "to_db_percent",

    # Helpers
    "json_safe", "as_int", "U", "disp", "B", "ensure_wd_conf_ge_dep",
    "stable_set", "memo_required_set", "fiat_set",
    "get_any_enabled_keys", "infer_asset_kind",
]


# =========================
# Identity
# =========================
UA = "swapers-sync/1.0 (+https://github.com/Desead/swapers)"


# =========================
# DB Decimal geometry (amounts)
# =========================
DB_INT_DIGITS   = int(getattr(settings, "DECIMAL_AMOUNT_INT_DIGITS", 18))
DB_DEC_PLACES   = int(getattr(settings, "DECIMAL_AMOUNT_DEC_PLACES", 10))
DB_QUANT        = Decimal(1).scaleb(-DB_DEC_PLACES)                         # 10^-dec
_DB_WALL        = (Decimal(10) ** DB_INT_DIGITS) - DB_QUANT                 # e.g. 1e18 - 1e-10 (…9999)
DB_MAX_AMOUNT   = _DB_WALL
# SAFE max: на один квант ниже «стены», чтобы не “перепрыгивало” в 1e18 из-за округлений
DB_MAX_AMOUNT_SAFE = DB_MAX_AMOUNT - DB_QUANT                               # …9998


# =========================
# Calculation geometry (amounts)
# =========================
_CALC_OFFSET        = int(getattr(settings, "DECIMAL_CALC_INT_OFFSET", 1))
CALC_INT_DIGITS     = max(1, DB_INT_DIGITS - _CALC_OFFSET)                  # usually 17
CALC_DEC_PLACES     = DB_DEC_PLACES                                         # 10
CALC_QUANT          = Decimal(1).scaleb(-CALC_DEC_PLACES)
# ещё безопаснее относительно «стены» расчётов
_CALC_WALL          = (Decimal(10) ** CALC_INT_DIGITS) - CALC_QUANT
CALC_MAX_AMOUNT     = _CALC_WALL - CALC_QUANT


# =========================
# Percents
# =========================
PERCENT_PLACES_DB   = int(getattr(settings, "DECIMAL_PERCENT_PLACES_DB", 5))
PERCENT_PLACES_CALC = int(getattr(settings, "DECIMAL_PERCENT_PLACES_CALC", 6))
PERCENT_QUANT_DB    = Decimal(1).scaleb(-PERCENT_PLACES_DB)                 # 10^-5
PERCENT_QUANT_CALC  = Decimal(1).scaleb(-PERCENT_PLACES_CALC)               # 10^-6
MAX_PERCENT         = Decimal("100")


# =========================
# Business limits for crypto withdraw (centralized)
# =========================
# Можно переопределить в settings.py при желании.
CRYPTO_WD_MIN_MIN     = Decimal(str(getattr(settings, "CRYPTO_WD_MIN_MIN", "0")))         # строго > 0
CRYPTO_WD_MIN_MAX     = Decimal(str(getattr(settings, "CRYPTO_WD_MIN_MAX", "100000")))    # <= 100000
CRYPTO_WD_FEE_FIX_MAX = Decimal(str(getattr(settings, "CRYPTO_WD_FEE_FIX_MAX", "100000")))# <= 100000


# =========================
# Base numeric helpers
# =========================

_NUM_TOKENS_NULL = {
    "", "na", "n/a", "nan", "null", "none", "-", "—",
    "inf", "infinity", "-inf", "-infinity", "+inf", "+infinity"
}

def _sanitize_number_like(x: Any) -> str:
    if isinstance(x, (int, float, Decimal)):
        return str(x)
    s = str(x or "").strip()
    if s.lower() in _NUM_TOKENS_NULL:
        return "0"
    s = s.replace("\u00a0", "").replace(" ", "").replace("_", "")
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?", s)
    if not m:
        return "0"
    token = m.group(0)
    if "," in token and "." not in token:
        token = token.replace(",", ".")
    return token


def D(x: Any) -> Decimal:
    """
    «Мягкое» Decimal-приведение:
    - чистим мусор/локали/NaN/Inf → 0;
    - клип по модулю к DB_MAX_AMOUNT_SAFE (на один квант ниже стены).
    """
    try:
        d = x if isinstance(x, Decimal) else Decimal(_sanitize_number_like(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")

    if not d.is_finite():
        return Decimal("0")

    if d > DB_MAX_AMOUNT_SAFE:
        return DB_MAX_AMOUNT_SAFE
    if d < -DB_MAX_AMOUNT_SAFE:
        return -DB_MAX_AMOUNT_SAFE
    return d


# =========================
# Calculation regime
# =========================

def to_calc_amount(value: Any, prec: int, *, allow_negative: bool = False) -> Decimal:
    """
    Нормализация суммы ДЛЯ РАСЧЁТОВ:
    - клип к CALC_MAX_AMOUNT;
    - prec в [0..DB_DEC_PLACES];
    - округление ROUND_DOWN;
    - если allow_negative=False, отрицательные → 0.
    """
    d = D(value)
    if not allow_negative and d < 0:
        d = Decimal("0")

    if d > CALC_MAX_AMOUNT:
        d = CALC_MAX_AMOUNT
    if d < -CALC_MAX_AMOUNT:
        d = -CALC_MAX_AMOUNT

    if prec < 0:
        prec = 0
    if prec > DB_DEC_PLACES:
        prec = DB_DEC_PLACES

    if d == 0:
        return d

    q = Decimal(1).scaleb(-prec)
    try:
        return d.quantize(q, rounding=ROUND_DOWN)
    except InvalidOperation:
        s = f"{d:f}"
        if "." in s and prec >= 0:
            head, tail = s.split(".", 1)
            return D(f"{head}.{tail[:prec]}")
        return D(s)


def to_calc_percent(value: Any) -> Decimal:
    """Процент ДЛЯ РАСЧЁТОВ: [0..100], 6 знаков, ROUND_HALF_UP."""
    d = D(value)
    if d < 0:
        d = Decimal("0")
    if d > MAX_PERCENT:
        d = MAX_PERCENT
    try:
        return d.quantize(PERCENT_QUANT_CALC, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return Decimal("0")


# =========================
# DB regime
# =========================

def to_db_amount(value: Any, prec: int, *, allow_negative: bool = False) -> Decimal:
    """
    Нормализация суммы ДЛЯ ЗАПИСИ В БД:
    1) to_calc_amount(...)  — клип к CALC_MAX и квантизация по prec,
    2) клип к DB_MAX_AMOUNT_SAFE,
    3) финальный quantize до DB_DEC_PLACES (DB_QUANT), ROUND_DOWN.
    """
    d = to_calc_amount(value, prec, allow_negative=allow_negative)

    if d > DB_MAX_AMOUNT_SAFE:
        d = DB_MAX_AMOUNT_SAFE
    if d < -DB_MAX_AMOUNT_SAFE:
        d = -DB_MAX_AMOUNT_SAFE

    try:
        return d.quantize(DB_QUANT, rounding=ROUND_DOWN)
    except InvalidOperation:
        s = f"{d:f}"
        if "." in s:
            head, tail = s.split(".", 1)
            tail = (tail + "0" * DB_DEC_PLACES)[:DB_DEC_PLACES]
            return D(f"{head}.{tail}")
        return D(s)


def to_db_percent(value: Any) -> Decimal:
    """Процент ДЛЯ ЗАПИСИ В БД: [0..100], 5 знаков, ROUND_HALF_UP."""
    d = D(value)
    if d < 0:
        d = Decimal("0")
    if d > MAX_PERCENT:
        d = MAX_PERCENT
    try:
        return d.quantize(PERCENT_QUANT_DB, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return Decimal("0")


# =========================
# Central crypto-withdraw guard
# =========================

def crypto_withdraw_guard(wd_min: Any, wd_fee_fixed: Any, prec: int) -> tuple[bool, Decimal, Decimal]:
    """
    Централизованный фильтр для КРИПТО-активов (применяем в провайдерах):
      1) минимальный вывод > 0
      2) минимальный вывод <= CRYPTO_WD_MIN_MAX
      3) фиксированная комиссия вывода <= CRYPTO_WD_FEE_FIX_MAX

    Возвращает: (ok, wd_min_q, wd_fee_fix_q) — ok=false => сеть/монету лучше пропустить.
    Значения wd_min_q и wd_fee_fix_q уже нормализованы под БД (to_db_amount(..., prec)).
    """
    min_q = to_db_amount(wd_min, prec)
    fee_q = to_db_amount(wd_fee_fixed, prec)

    zero_q   = to_db_amount(CRYPTO_WD_MIN_MIN, prec)
    min_max  = to_db_amount(CRYPTO_WD_MIN_MAX, prec)
    fee_max  = to_db_amount(CRYPTO_WD_FEE_FIX_MAX, prec)

    ok = (min_q > zero_q) and (min_q <= min_max) and (fee_q <= fee_max)
    return ok, min_q, fee_q


# =========================
# Misc helpers
# =========================

def json_safe(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, dict):
        return {k: json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [json_safe(v) for v in o]
    return o


def as_int(x: Any, default: int = 0, *, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        v = int(D(x))
    except Exception:
        v = default
    if min_value is not None and v < min_value:
        v = min_value
    if max_value is not None and v > max_value:
        v = max_value
    return v


def U(s: Optional[str]) -> str:
    return (s or "").strip().upper()


def disp(s: Optional[str]) -> str:
    return (s or "").strip()


def B(*vals: Any) -> bool:
    for x in vals:
        if isinstance(x, bool):
            return x
        if isinstance(x, (int, float)):
            return bool(x)
        if isinstance(x, str):
            v = x.strip().lower()
            if v in {"1", "true", "yes", "y", "on", "enabled", "allow", "allowed"}:
                return True
            if v in {"0", "false", "no", "n", "off", "disabled", "deny", "denied"}:
                return False
    return False


def ensure_wd_conf_ge_dep(dep_conf: int, wd_conf: int) -> tuple[int, int]:
    if wd_conf < dep_conf:
        wd_conf = dep_conf
    return dep_conf, wd_conf


# =========================
# SiteSetup helpers
# =========================

def _split_tokens(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [p for p in re.split(r"[\s,;]+", raw) if p]
    if isinstance(raw, (list, tuple)):
        return [str(p) for p in raw if str(p).strip()]
    return []


def stable_set() -> Set[str]:
    ss = SiteSetup.get_solo()
    return {U(x) for x in _split_tokens(getattr(ss, "stablecoins", "") or "")}


def memo_required_set() -> Set[str]:
    ss = SiteSetup.get_solo()
    try:
        s = ss.get_memo_required_chains_set()  # type: ignore[attr-defined]
        return {U(x) for x in s}
    except Exception:
        raw = getattr(ss, "memo_required_chains", "") or ""
        return {U(x) for x in _split_tokens(raw)}


def fiat_set() -> Set[str]:
    ss = SiteSetup.get_solo()
    raw = (getattr(ss, "fiat_name", "") or "").strip()
    items = {U(x) for x in _split_tokens(raw)}
    return items or {
        "USD", "EUR", "GBP", "CHF", "JPY", "CNY", "AUD", "CAD", "NZD",
        "SEK", "NOK", "DKK", "RUB", "UAH", "KZT", "TRY", "BRL", "MXN",
        "PLN", "CZK", "HUF", "AED", "SAR", "ILS", "HKD", "SGD", "INR", "ZAR"
    }


# =========================
# Provider utilities
# =========================

def get_any_enabled_keys(exchange) -> tuple[Optional[str], Optional[str]]:
    rec = (
        ExchangeApiKey.objects
        .filter(exchange=exchange, is_enabled=True)
        .order_by("id")
        .only("api_key", "api_secret")
        .first()
    )
    return ((rec.api_key or None), (rec.api_secret or None)) if rec else (None, None)


def infer_asset_kind(asset_code: str, chain_code: str, chain_name: str, *, fiat_codes: Optional[Set[str]] = None) -> AssetKind:
    ac = U(asset_code)
    cc = U(chain_code)
    disp_name = U(chain_name)
    fiat_codes = fiat_codes or fiat_set()

    FIAT_HINTS = {"FIAT", "BANK", "WIRE", "SEPA", "SWIFT", "CARD", "FUNDING", "PAY", "PAYMENT"}
    if ac in fiat_codes or cc in FIAT_HINTS or any(h in disp_name for h in FIAT_HINTS):
        return AssetKind.FIAT
    return AssetKind.CRYPTO
