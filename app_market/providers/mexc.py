from __future__ import annotations

import hashlib
import hmac
import json
import socket
import time
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Dict, Iterable, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.utils.timezone import now

from app_market.models import Exchange, ExchangeAsset, ExchangeApiKey
from app_market.models.exchange_asset import AssetKind
from app_main.models import SiteSetup
from .base import ProviderAdapter, AssetSyncStats

UA = "swapers-sync/1.0 (+https://github.com/Desead/swapers)"
BASE = "https://api.mexc.com"

# ------------ Decimal helpers (кап, квантизация, NaN/Inf-safe) -------------
_BIGNUM = Decimal("1e20")
_ZERO = Decimal("0")


def _dec_ok(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, (int, float, Decimal)):
        return True
    s = str(v).strip()
    if not s:
        return False
    up = s.upper()
    if up in ("NAN", "INF", "+INF", "-INF", "INFINITY", "+INFINITY", "-INFINITY"):
        return False
    return True


def _q_amt(v: Any, places: int = 10) -> Decimal:
    try:
        if not _dec_ok(v):
            return _ZERO
        d = Decimal(str(v))
        if d.is_nan() or d.is_infinite():
            return _ZERO
        if d < 0:
            d = -d
        if d > _BIGNUM:
            d = _BIGNUM
        q = Decimal(1).scaleb(-places)
        return d.quantize(q, rounding=ROUND_DOWN)
    except InvalidOperation:
        return _ZERO


def _q_pct(v: Any, places: int = 5) -> Decimal:
    d = _q_amt(v, places=places)
    return Decimal("100") if d > Decimal("100") else d


def _to_bool(*vals: Any) -> bool:
    for v in vals:
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("true", "1", "yes", "y", "on"):
            return True
        if s in ("false", "0", "no", "n", "off"):
            return False
    return False


def _pick(*vals: Any, default: Any = None) -> Any:
    for v in vals:
        if v is not None:
            return v
    return default


# ------------------------- DNS preflight probe ------------------------------
def _probe_dns(host: str = "api.mexc.com", attempts: int = 2, pause: float = 0.25) -> tuple[bool, str]:
    last = ""
    for _ in range(attempts):
        try:
            socket.getaddrinfo(host, 443, 0, 0, 0, socket.AI_ADDRCONFIG)
            return True, ""
        except socket.gaierror as e:
            last = f"{e.errno} {e.strerror or e}"
            time.sleep(pause)
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(pause)
    return False, last


# ----------------------------- Signing/HTTP --------------------------------
def _mexc_sign(secret: str, query: str) -> str:
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _get_api_key_pair(exchange: Exchange) -> tuple[str, str]:
    key = (
        ExchangeApiKey.objects.filter(exchange=exchange, is_enabled=True)
        .order_by("id")
        .first()
    )
    if not key or not key.api_key or not key.api_secret:
        raise RuntimeError("MEXC: не найдены активные API-ключи для этого провайдера")
    return key.api_key.strip(), key.api_secret.strip()


def _http_get_json_signed(path: str, api_key: str, secret: str, timeout: int = 15) -> Any:
    ts = int(time.time() * 1000)
    qs = urlencode({"timestamp": ts, "recvWindow": 20000})
    sig = _mexc_sign(secret, qs)
    url = f"{BASE}{path}?{qs}&signature={sig}"

    req = Request(url, method="GET")
    req.add_header("User-Agent", UA)
    req.add_header("X-MEXC-APIKEY", api_key)
    # ВАЖНО: не ставим Content-Type для GET, иначе 400 Invalid content Type

    last_err = None
    for attempt in range(2):  # лёгкий ретрай
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                body = ""
            last_err = f"HTTP {e.code}: {e.reason}; body={body}"
            # 4xx бессмысленно ретраить, но дадим одну паузу
            if 400 <= getattr(e, "code", 0) < 500:
                break
            time.sleep(0.4)
        except URLError as e:
            # Быстрый выход для Windows-кодов DNS: 11001/11004
            reason = getattr(e, "reason", "")
            if any(code in str(reason) for code in ("11001", "11004")):
                last_err = f"URLError (DNS): {reason}"
                break
            last_err = f"URLError: {reason}"
            time.sleep(0.4)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(0.4)
    raise RuntimeError(f"MEXC: ошибка запросов: {last_err or 'unknown'}")


# ----------------------------- Payload parse --------------------------------
def _iter_network_rows(payload: Any) -> Iterable[Dict[str, Any]]:
    if not isinstance(payload, list):
        return
    for coin_obj in payload:
        asset_code = str(_pick(coin_obj.get("coin"), coin_obj.get("asset"), "")).strip().upper()
        if not asset_code:
            continue
        asset_name = str(_pick(coin_obj.get("name"), coin_obj.get("fullName"), asset_code)).strip()
        nets = coin_obj.get("networkList") or coin_obj.get("chains") or []
        if not isinstance(nets, list):
            continue
        for net in nets:
            chain_code = str(_pick(net.get("network"), net.get("chain"), net.get("name"), "")).strip().upper()
            if not chain_code:
                continue
            yield {
                "asset_code": asset_code,
                "asset_name": asset_name or asset_code,
                "chain_code": chain_code,
                "chain_display": str(_pick(net.get("network"), net.get("chain"), net.get("name"), chain_code)).strip(),
                "deposit_enable": _to_bool(net.get("depositEnable"), net.get("canDeposit")),
                "withdraw_enable": _to_bool(net.get("withdrawEnable"), net.get("canWithdraw")),
                "deposit_min": _q_amt(net.get("depositMin")),
                "deposit_max": _q_amt(net.get("depositMax")),
                "withdraw_min": _q_amt(net.get("withdrawMin")),
                "withdraw_max": _q_amt(net.get("withdrawMax")),
                "withdraw_fee_fixed": _q_amt(net.get("withdrawFee")),
                "deposit_fee_percent": _ZERO,
                "withdraw_fee_percent": _ZERO,
                "deposit_fee_fixed": _q_amt(net.get("depositFee") or net.get("depositFeeFixed")),
                "confirm_deposit": int(_pick(net.get("minConfirm"), net.get("confirmTimes"), 0) or 0),
                "need_tag": _to_bool(net.get("needTag")),
                "special_tips": str(net.get("specialTips") or ""),
                "raw": net,
            }


# ------------------------- kind inference (FIAT/CRYPTO) ---------------------
def _infer_asset_kind(asset_code: str, chain_code: str, chain_display: str) -> AssetKind:
    """
    Простая эвристика:
    - FIAT, если сеть/отображаемое имя указывает на банковские/фиатные рельсы
      (FIAT/BANK/WIRE/SEPA/SWIFT/CARD/PAY/PAYMENT/FUNDING),
      или сам тикер — очевидная фиатная валюта.
    - Иначе CRYPTO.
    """
    ac = (asset_code or "").upper()
    cc = (chain_code or "").upper()
    disp = (chain_display or "").upper()

    FIAT_TOKENS = {"USD", "EUR", "RUB", "UAH", "BRL", "TRY", "GBP", "KZT", "AUD", "CHF", "CAD", "JPY"}
    FIAT_HINTS = {"FIAT", "BANK", "WIRE", "SEPA", "SWIFT", "CARD", "FUNDING", "PAY", "PAYMENT"}

    if cc in FIAT_HINTS or any(h in disp for h in FIAT_HINTS) or ac in FIAT_TOKENS:
        return AssetKind.FIAT
    return AssetKind.CRYPTO


# -------------------------------- Adapter -----------------------------------
class MexcAdapter(ProviderAdapter):
    code = "MEXC"
    title = "MEXC"

    def sync_assets(
        self,
        exchange: Exchange,
        timeout: int = 15,
        limit: int | None = None,
        reconcile: bool = True,
        verbose: bool = False,
    ) -> AssetSyncStats:
        stats = AssetSyncStats()

        # DNS препроба — быстро выходим, если нет резолвинга
        ok, why = _probe_dns("api.mexc.com")
        if not ok:
            if verbose:
                print(f"[MEXC][SKIP] DNS resolve failed: {why}")
            return stats  # пустые processed/updated и т.д.

        api_key, api_secret = _get_api_key_pair(exchange)
        payload = _http_get_json_signed("/api/v3/capital/config/getall", api_key, api_secret, timeout=timeout)

        setup = SiteSetup.get_solo()
        stable_set = {s.strip().upper() for s in (setup.stablecoins or "").replace(",", " ").split() if s.strip()}
        memo_chains = setup.get_memo_required_chains_set()

        processed = created = updated = skipped = 0
        seen_pairs: set[tuple[str, str]] = set()

        for row in _iter_network_rows(payload):
            processed += 1
            if limit and processed > limit:
                break

            asset_code = row["asset_code"]
            chain_code = row["chain_code"]
            chain_display = row["chain_display"]
            seen_pairs.add((asset_code, chain_code))

            # kind (FIAT/CRYPTO)
            asset_kind = _infer_asset_kind(asset_code, chain_code, chain_display)

            # memo: сеть/текст/список из SiteSetup
            requires_memo = bool(row["need_tag"])
            if not requires_memo:
                txt = (row["special_tips"] or "").lower()
                if "memo" in txt or "tag" in txt:
                    requires_memo = True
            if not requires_memo and chain_code in memo_chains:
                requires_memo = True

            # подтверждения
            if asset_kind == AssetKind.CRYPTO:
                conf_dep = max(1, int(row["confirm_deposit"]))
                conf_wdr = max(conf_dep, int(row["confirm_deposit"]))  # у MEXC обычно одно число; вывод не меньше
            else:
                conf_dep = 0
                conf_wdr = 0

            defaults: Dict[str, Any] = {
                "asset_name": row["asset_name"],
                "chain_display": chain_display,
                "AD": bool(row["deposit_enable"]),
                "AW": bool(row["withdraw_enable"]),
                "confirmations_deposit": conf_dep,
                "confirmations_withdraw": conf_wdr,
                "deposit_fee_percent": _q_pct(row["deposit_fee_percent"]),
                "deposit_fee_fixed": _q_amt(row["deposit_fee_fixed"]),
                "deposit_min": _q_amt(row["deposit_min"]),
                "deposit_max": _q_amt(row["deposit_max"]),
                "withdraw_fee_percent": _q_pct(row["withdraw_fee_percent"]),
                "withdraw_fee_fixed": _q_amt(row["withdraw_fee_fixed"]),
                "withdraw_min": _q_amt(row["withdraw_min"]),
                "withdraw_max": _q_amt(row["withdraw_max"]),
                "asset_kind": asset_kind,
                "amount_precision": 8,
                "amount_precision_display": 5,
                "nominal": 1,
                "requires_memo": requires_memo,
                "is_stablecoin": (asset_code.upper() in stable_set),
                "provider_symbol": asset_code,
                "provider_chain": chain_code,
            }

            obj, was_created = ExchangeAsset.objects.get_or_create(
                exchange=exchange,
                asset_code=asset_code,
                chain_code=chain_code,
                defaults={**defaults, "raw_metadata": row["raw"], "last_synced_at": now()},
            )
            if was_created:
                created += 1
                continue

            changed: Dict[str, Any] = {}
            for f in (
                "asset_name", "chain_display",
                "AD", "AW",
                "confirmations_deposit", "confirmations_withdraw",
                "deposit_fee_percent", "deposit_fee_fixed", "deposit_min", "deposit_max",
                "withdraw_fee_percent", "withdraw_fee_fixed", "withdraw_min", "withdraw_max",
                "asset_kind", "amount_precision", "amount_precision_display", "nominal",
                "requires_memo", "is_stablecoin",
                "provider_symbol", "provider_chain",
            ):
                new_val = defaults[f]
                old_val = getattr(obj, f)
                if isinstance(new_val, Decimal) and isinstance(old_val, Decimal):
                    if new_val.normalize() != old_val.normalize():
                        changed[f] = new_val
                else:
                    if new_val != old_val:
                        changed[f] = new_val

            if changed:
                changed["raw_metadata"] = row["raw"]
                changed["last_synced_at"] = now()
                ExchangeAsset.objects.filter(pk=obj.pk).update(**changed)
                updated += 1
            else:
                ExchangeAsset.objects.filter(pk=obj.pk).update(last_synced_at=now())
                skipped += 1

        stats.processed = processed
        stats.created = created
        stats.updated = updated
        stats.skipped = skipped
        stats.disabled = 0

        if reconcile:
            known = set(
                ExchangeAsset.objects.filter(exchange=exchange).values_list("asset_code", "chain_code")
            )
            missing = known - seen_pairs
            if missing:
                q = ExchangeAsset.objects.filter(exchange=exchange)
                for a, c in missing:
                    q.filter(asset_code=a, chain_code=c).update(AD=False, AW=False)

        if verbose:
            print(f"[MEXC] processed={processed} created={created} updated={updated} skipped={skipped} disabled={stats.disabled}")

        return stats
