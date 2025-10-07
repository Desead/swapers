from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Iterable, Optional, Set, Tuple

from app_main.models import SiteSetup
from app_market.models.exchange_asset import AssetKind
from app_market.models.account import ExchangeApiKey

_NUM_TOKENS_NULL = {"", "na", "n/a", "nan", "null", "none", "-", "—", "inf", "infinity", "-inf", "-infinity", "+inf", "+infinity"}

__all__ = [
    # Константы
    "MAX_ABS_AMOUNT", "MAX_PERCENT", "PERCENT_QUANT", "MAX_AMOUNT_PREC", "UA",

    # Числовые утилиты
    "D", "q_amount", "q_percent", "json_safe", "as_int",

    # Строки/булево/прочее
    "U", "disp", "B", "ensure_wd_conf_ge_dep",

    # Доступ к SiteSetup
    "stable_set", "memo_required_set", "fiat_set",

    # Утилиты для провайдеров
    "get_any_enabled_keys", "infer_asset_kind",
]

# ===== Константы и параметры нормализации =====

UA = "swapers-sync/1.0 (+https://github.com/Desead/swapers)"

# ⚠️ Модели ExchangeAsset: суммы/лимиты/фиксы — DecimalField(28,10)
# Значит максимум 18 целых и 10 дробных. Кэп делаем под это поле.
MAX_ABS_AMOUNT = Decimal("999999999999999999.9999999999")

# Лимит процентов (0..100)
MAX_PERCENT = Decimal("100")

# Квант для процентов: ровно 5 знаков после запятой (совместимо с DecimalField(..., 5))
PERCENT_QUANT = Decimal("0.00001")

# Максимальная точность *сумм* для хранения в БД: 10 знаков (как в моделях)
MAX_AMOUNT_PREC = 10


# ===== Базовые утилиты Decimal =====
def _sanitize_number_like(x: Any) -> str:
    if isinstance(x, (int, float, Decimal)):
        return str(x)
    s = str(x or "").strip()
    s_low = s.lower()
    if s_low in _NUM_TOKENS_NULL:
        return "0"
    s = s.replace("\u00a0", "").replace(" ", "").replace("_", "")
    import re as _re
    m = _re.search(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?", s)
    if not m:
        return "0"
    token = m.group(0)
    if "," in token and "." not in token:
        token = token.replace(",", ".")
    return token


def D(x: Any) -> Decimal:
    """«Мягко» превращает значение в Decimal; NaN/Inf/None/ошибки → 0; кап по модулю."""
    try:
        if isinstance(x, Decimal):
            d = x
        else:
            d = Decimal(_sanitize_number_like(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")

    if not d.is_finite():
        return Decimal("0")

    if d > MAX_ABS_AMOUNT:
        return MAX_ABS_AMOUNT
    if d < -MAX_ABS_AMOUNT:
        return -MAX_ABS_AMOUNT
    return d


def q_amount(value: Any, prec: int, *, allow_negative: bool = False) -> Decimal:
    """
    Квантизация сумм/лимитов/фикс-комиссий по точности `prec`:
    - отрицательные → 0 (если allow_negative=False)
    - prec зажимается в [0..MAX_AMOUNT_PREC] (модель хранит до 10 знаков)
    - округление ROUND_DOWN
    """
    d = D(value)
    if not allow_negative and d < 0:
        d = Decimal("0")

    if prec < 0:
        prec = 0
    if prec > MAX_AMOUNT_PREC:
        prec = MAX_AMOUNT_PREC

    if d == 0:
        return d

    q = Decimal(1).scaleb(-prec)  # 10^-prec
    try:
        return d.quantize(q, rounding=ROUND_DOWN)
    except InvalidOperation:
        s = f"{d:f}"
        if "." in s and prec >= 0:
            head, tail = s.split(".", 1)
            return D(f"{head}.{tail[:prec]}")
        return D(s)


def q_percent(value: Any) -> Decimal:
    """Проценты: диапазон [0..100], 5 знаков, ROUND_HALF_UP."""
    d = D(value)
    if d < 0:
        d = Decimal("0")
    if d > MAX_PERCENT:
        d = MAX_PERCENT
    try:
        return d.quantize(PERCENT_QUANT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return Decimal("0")


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


# ===== Строки/булево/прочее =====
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


# ===== SiteSetup =====
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


# ===== Провайдерные утилиты =====
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
