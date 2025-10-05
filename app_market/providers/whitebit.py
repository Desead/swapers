from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Dict, Optional, Set, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from django.db import transaction
from django.utils import timezone

from app_market.models.exchange import Exchange
from app_market.models.exchange_asset import ExchangeAsset, AssetKind
from app_market.models.account import ExchangeApiKey
from app_main.models import SiteSetup
from .base import ProviderAdapter, AssetSyncStats

WB_BASE = "https://whitebit.com"
ASSETS_URL = f"{WB_BASE}/api/v4/public/assets"
FEE_URL = f"{WB_BASE}/api/v4/public/fee"
PRIV_FEE_PATH = "/api/v4/main-account/fee"
PRIV_FEE_URL = f"{WB_BASE}{PRIV_FEE_PATH}"
UA = "swapers-sync/1.0 (+https://github.com/Desead/swapers)"

# === Helpers: HTTP с ретраями ===

def _http_get_json(url: str, timeout: int = 20, retries: int = 3) -> Any:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as e:
            last_exc = e
            if attempt < retries - 1:
                # экспоненциальный backoff 0.5, 1.0, 2.0
                time.sleep(0.5 * (2 ** attempt))
            else:
                break
    raise RuntimeError(f"WhiteBIT: ошибка запросов: {last_exc}")

def _http_post_signed_json(url: str, body: dict, api_key: str, api_secret: str, timeout: int = 30, retries: int = 3) -> Any:
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    b64 = base64.b64encode(payload)
    sign = hmac.new(api_secret.encode("utf-8"), b64, hashlib.sha512).hexdigest()

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(
                url,
                data=payload,
                headers={
                    "User-Agent": UA,
                    "Content-Type": "application/json",
                    "X-TXC-APIKEY": api_key,
                    "X-TXC-PAYLOAD": b64.decode("ascii"),
                    "X-TXC-SIGNATURE": sign,
                },
                method="POST",
            )
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(0.5 * (2 ** attempt))
            else:
                break
    raise RuntimeError(f"WhiteBIT: ошибка запросов: {last_exc}")

# === Helpers: безопасные Decimal и квантизация ===

_MAX_ABS = Decimal("1e20")  # здравый кап на суммы/лимиты/фикс.комиссии

def _D(x: Any) -> Decimal:
    """Мягкое превращение в Decimal без NaN/Inf."""
    try:
        if isinstance(x, Decimal):
            d = x
        elif x in (None, "", "0E-10"):
            d = Decimal("0")
        else:
            d = Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")

    # NaN / Inf → 0
    if not d.is_finite():
        return Decimal("0")
    # кап значений
    if d > _MAX_ABS:
        return _MAX_ABS
    if d < -_MAX_ABS:
        return -_MAX_ABS
    return d

def _B(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    if isinstance(x, str):
        v = x.strip().lower()
        return v in {"1", "true", "yes", "y", "on", "enabled", "allow", "allowed"}
    return False

def _upper(s: Optional[str]) -> str:
    return (s or "").strip().upper()

def _disp(s: Optional[str]) -> str:
    return (s or "").strip()

def _json_safe(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return o

def _q_amount(value: Any, prec: int) -> Decimal:
    """Квантизация сумм/лимитов/фиксов по точности актива (ROUND_DOWN)."""
    d = _D(value)
    if d == 0:
        return d
    if prec < 0:
        prec = 0
    if prec > 18:
        prec = 18
    q = Decimal(1).scaleb(-prec)  # 10^-prec
    # отрицательных лимитов/комиссий по фикс-сумме не допускаем
    if d < 0:
        d = Decimal("0")
    try:
        return d.quantize(q, rounding=ROUND_DOWN)
    except InvalidOperation:
        # в крайнем случае обрежем строкой
        s = f"{d:f}"
        if "." in s:
            head, tail = s.split(".", 1)
            return _D(f"{head}.{tail[:prec]}")
        return _D(s)

def _q_percent(value: Any) -> Decimal:
    """Проценты → [0..100], 5 знаков, ROUND_HALF_UP."""
    d = _D(value)
    if d < 0:
        d = Decimal("0")
    if d > Decimal("100"):
        d = Decimal("100")
    try:
        return d.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return Decimal("0")

# === SiteSetup helpers ===

def _stable_set_from_sitesetup() -> Set[str]:
    ss = SiteSetup.get_solo()
    raw = ss.stablecoins
    items: list[str] = []
    if isinstance(raw, str):
        items = [p for p in re.split(r"[\s,;]+", raw) if p]
    elif isinstance(raw, (list, tuple)):
        items = [str(p) for p in raw if p]
    return {p.strip().upper() for p in items}

def _memo_required_set() -> Set[str]:
    ss = SiteSetup.get_solo()
    try:
        return ss.get_memo_required_chains_set()
    except Exception:
        raw = (getattr(ss, "memo_required_chains", "") or "").strip()
        if not raw:
            return set()
        return {p.strip().upper() for p in re.split(r"[\s,;]+", raw) if p.strip()}

# === Парсинг публичных структур ===

@dataclass
class FeeSide:
    min_amount: Decimal = Decimal("0")
    max_amount: Decimal = Decimal("0")
    fixed: Decimal = Decimal("0")
    percent: Decimal = Decimal("0")

@dataclass
class FeePack:
    deposit: FeeSide
    withdraw: FeeSide

def _flex_percent(v: Any) -> Decimal:
    if isinstance(v, dict):
        return _D(v.get("percent"))
    return _D(v)

def _parse_public_fee(obj: dict) -> Dict[Tuple[str, Optional[str]], FeePack]:
    out: Dict[Tuple[str, Optional[str]], FeePack] = {}
    for key, row in obj.items():
        if not isinstance(row, dict):
            continue
        m = re.match(r"^\s*([A-Za-z0-9]+)\s*(?:\(\s*([^)]+)\s*\))?\s*$", str(key))
        ticker = (m.group(1) if m else str(key)).strip().upper()
        network = (m.group(2).strip().upper() if (m and m.group(2)) else None)

        dep = row.get("deposit") or {}
        wd = row.get("withdraw") or {}

        out[(ticker, network)] = FeePack(
            deposit=FeeSide(
                min_amount=_D(dep.get("min_amount")),
                max_amount=_D(dep.get("max_amount")),
                fixed=_D(dep.get("fixed")),
                percent=_flex_percent(dep.get("flex")),
            ),
            withdraw=FeeSide(
                min_amount=_D(wd.get("min_amount")),
                max_amount=_D(wd.get("max_amount")),
                fixed=_D(wd.get("fixed")),
                percent=_flex_percent(wd.get("flex")),
            ),
        )
    return out

def _parse_public_assets(obj: dict) -> Dict[Tuple[str, Optional[str]], dict]:
    result: Dict[Tuple[str, Optional[str]], dict] = {}
    for ticker, payload in obj.items():
        if not isinstance(payload, dict):
            continue
        t = _upper(ticker)
        name = _disp(payload.get("name")) or t
        precision = int(payload.get("currency_precision") or 8)
        requires_memo = _B(payload.get("is_memo"))
        can_dep_global = _B(payload.get("can_deposit"))
        can_wd_global = _B(payload.get("can_withdraw"))

        is_fiat = isinstance(payload.get("providers"), dict)
        asset_kind = AssetKind.FIAT if is_fiat else AssetKind.CRYPTO

        networks = payload.get("networks") or {}
        nets_dep = set(networks.get("deposits") or [])
        nets_wd = set(networks.get("withdraws") or [])
        confirms: dict = payload.get("confirmations") or {}

        limits = payload.get("limits") or {}
        lim_dep: dict = limits.get("deposit") or {}
        lim_wd: dict = limits.get("withdraw") or {}

        nets_all = sorted(set(nets_dep) | set(nets_wd) | set(confirms.keys()) | set(lim_dep.keys()) | set(lim_wd.keys()))
        if not nets_all:
            key = (t, None)
            result[key] = {
                "asset_name": name,
                "amount_precision": precision,
                "requires_memo": requires_memo,
                "asset_kind": asset_kind,
                "can_deposit": can_dep_global,
                "can_withdraw": can_wd_global,
                "confirmations": int(payload.get("confirmations") or 0),
                "deposit_limits": {"min": _D(payload.get("min_deposit")), "max": _D(payload.get("max_deposit"))},
                "withdraw_limits": {"min": _D(payload.get("min_withdraw")), "max": _D(payload.get("max_withdraw"))},
            }
            continue

        for net in nets_all:
            key = (t, str(net).strip().upper())
            dep_ok = can_dep_global and (not nets_dep or net in nets_dep)
            wd_ok = can_wd_global and (not nets_wd or net in nets_wd)
            result[key] = {
                "asset_name": name,
                "amount_precision": precision,
                "requires_memo": requires_memo,
                "asset_kind": asset_kind,
                "can_deposit": dep_ok,
                "can_withdraw": wd_ok,
                "confirmations": int((confirms or {}).get(net) or 0),
                "deposit_limits": {
                    "min": _D((lim_dep.get(net) or {}).get("min")),
                    "max": _D((lim_dep.get(net) or {}).get("max")),
                },
                "withdraw_limits": {
                    "min": _D((lim_wd.get(net) or {}).get("min")),
                    "max": _D((lim_wd.get(net) or {}).get("max")),
                },
            }
    return result

# === Ключи ===

def _get_any_enabled_keys(exchange: Exchange) -> tuple[Optional[str], Optional[str]]:
    key = (
        ExchangeApiKey.objects
        .filter(exchange=exchange, is_enabled=True)
        .order_by("id")
        .first()
    )
    return ((key.api_key or None), (key.api_secret or None)) if key else (None, None)

def _fetch_private_fee(api_key: str, api_secret: str, timeout: int = 30) -> Dict[str, dict]:
    body = {"request": PRIV_FEE_PATH, "nonce": int(time.time() * 1000)}
    data = _http_post_signed_json(PRIV_FEE_URL, body, api_key, api_secret, timeout=timeout)
    out: Dict[str, dict] = {}
    if isinstance(data, list):
        for row in data:
            t = _upper(row.get("ticker"))
            if t:
                out[t] = row
    return out

# === Внутренние строки для UPSERT ===

@dataclass
class _Row:
    ticker: str
    chain: Optional[str]
    name: str
    kind: str
    AD: bool
    AW: bool
    conf_dep: int
    conf_wd: int
    dep_min: Decimal
    dep_max: Decimal
    wd_min: Decimal
    wd_max: Decimal
    dep_fee_pct: Decimal
    dep_fee_fix: Decimal
    wd_fee_pct: Decimal
    wd_fee_fix: Decimal
    requires_memo: bool
    amount_precision: int
    raw_meta: dict
    is_stable: bool

# === Адаптер ===

class WhitebitAdapter(ProviderAdapter):
    code = "WHITEBIT"

    @transaction.atomic
    def sync_assets(
        self,
        exchange: Exchange,
        *,
        timeout: int = 20,
        limit: int = 0,
        reconcile: bool = True,
        verbose: bool = False,
    ) -> AssetSyncStats:
        stats = AssetSyncStats()
        stable_set = _stable_set_from_sitesetup()
        memo_set = _memo_required_set()

        # публичные структуры
        assets_json = _http_get_json(ASSETS_URL, timeout=timeout)
        fee_json = _http_get_json(FEE_URL, timeout=timeout)

        assets_map = _parse_public_assets(assets_json)
        pub_fee_map = _parse_public_fee(fee_json)

        # приватные комиссии (приоритетнее)
        api_key, api_secret = _get_any_enabled_keys(exchange)
        priv_fee_map: Dict[str, dict] = {}
        if api_key and api_secret:
            try:
                priv_fee_map = _fetch_private_fee(api_key, api_secret, timeout=timeout)
            except Exception:
                # приватный фид опционален — продолжаем с публичными
                priv_fee_map = {}

        def merge_fee(t: str, n: Optional[str]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
            """Возвращает (dep_pct, dep_fix, wd_pct, wd_fix) с приоритетом приватных значений."""
            priv = priv_fee_map.get(t) or {}
            if priv:
                d = priv.get("deposit") or {}
                w = priv.get("withdraw") or {}
                return (
                    _D(d.get("percentFlex")), _D(d.get("fixed")),
                    _D(w.get("percentFlex")), _D(w.get("fixed")),
                )
            pack = pub_fee_map.get((t, n)) or pub_fee_map.get((t, None))
            if pack:
                return (
                    pack.deposit.percent, pack.deposit.fixed,
                    pack.withdraw.percent, pack.withdraw.fixed,
                )
            return (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))

        # готовим строки
        rows: list[_Row] = []
        for (ticker, network), meta in assets_map.items():
            if limit and len(rows) >= limit:
                break
            kind = meta.get("asset_kind") or AssetKind.CRYPTO

            dep_conf = int(meta.get("confirmations") or 0)
            if kind == AssetKind.CRYPTO and dep_conf < 1:
                dep_conf = 1
            wd_conf = dep_conf  # отдельного не даёт публичка — берём минимум как dep_conf

            dep_lim = meta.get("deposit_limits") or {}
            wd_lim = meta.get("withdraw_limits") or {}

            dep_pct, dep_fix, wd_pct, wd_fix = merge_fee(ticker, network)

            provider_memo = bool(meta.get("requires_memo") or False)
            chain_norm = _upper(network or ticker)
            requires_memo = (kind == AssetKind.CRYPTO) and (provider_memo or (chain_norm in memo_set))

            rows.append(_Row(
                ticker=ticker,
                chain=network,
                name=_disp(meta.get("asset_name")) or ticker,
                kind=kind,
                AD=_B(meta.get("can_deposit")),
                AW=_B(meta.get("can_withdraw")),
                conf_dep=dep_conf,
                conf_wd=wd_conf,
                dep_min=_D(dep_lim.get("min")),
                dep_max=_D(dep_lim.get("max")),
                wd_min=_D(wd_lim.get("min")),
                wd_max=_D(wd_lim.get("max")),
                dep_fee_pct=dep_pct,
                dep_fee_fix=dep_fix,
                wd_fee_pct=wd_pct,
                wd_fee_fix=wd_fix,
                requires_memo=requires_memo,
                amount_precision=int(meta.get("amount_precision") or 8),
                raw_meta={"assets": _json_safe(meta)},
                is_stable=(kind == AssetKind.CRYPTO) and (ticker in stable_set),
            ))

        # UPSERT + reconcile
        seen: Set[Tuple[str, str]] = set()

        for r in rows:
            stats.processed += 1
            chain_code = (r.chain or r.ticker)
            seen.add((r.ticker, chain_code))

            # нормализуем значения перед сохранением
            prec = int(r.amount_precision or 8)
            new_vals = dict(
                asset_name=r.name,
                AD=bool(r.AD),
                AW=bool(r.AW),
                confirmations_deposit=int(r.conf_dep),
                confirmations_withdraw=int(max(r.conf_dep, r.conf_wd)),
                deposit_min=_q_amount(r.dep_min, prec),
                deposit_max=_q_amount(r.dep_max, prec),
                withdraw_min=_q_amount(r.wd_min, prec),
                withdraw_max=_q_amount(r.wd_max, prec),
                deposit_fee_percent=_q_percent(r.dep_fee_pct),
                deposit_fee_fixed=_q_amount(r.dep_fee_fix, prec),
                withdraw_fee_percent=_q_percent(r.wd_fee_pct),
                withdraw_fee_fixed=_q_amount(r.wd_fee_fix, prec),
                requires_memo=bool(r.requires_memo),
                is_stablecoin=bool(r.is_stable),
                amount_precision=prec,
                asset_kind=r.kind,
                provider_symbol=r.ticker,
                provider_chain=(r.chain or ""),
            )

            obj, created = ExchangeAsset.objects.get_or_create(
                exchange=exchange,
                asset_code=r.ticker,
                chain_code=chain_code,
                defaults={**new_vals, "raw_metadata": _json_safe(r.raw_meta), "chain_display": chain_code},
            )

            if created:
                stats.created += 1
            else:
                changed: list[str] = []
                for f, v in new_vals.items():
                    if getattr(obj, f) != v:
                        setattr(obj, f, v)
                        changed.append(f)

                if changed:
                    # raw_metadata обновляем ТОЛЬКО при реальном изменении деловых полей
                    obj.raw_metadata = _json_safe(r.raw_meta)
                    obj.save(update_fields=changed + ["raw_metadata", "updated_at"])
                    stats.updated += 1
                else:
                    stats.skipped += 1

        if reconcile:
            to_disable = []
            for obj in ExchangeAsset.objects.filter(exchange=exchange).only("id", "asset_code", "chain_code", "AD", "AW"):
                key = (obj.asset_code, obj.chain_code)
                if key not in seen and (obj.AD or obj.AW):
                    to_disable.append(obj.id)
            if to_disable:
                ExchangeAsset.objects.filter(id__in=to_disable).update(
                    AD=False, AW=False,
                    status_note="Отключено: отсутствует в выдаче WhiteBIT",
                    updated_at=timezone.now(),
                )
                stats.disabled = len(to_disable)

        if verbose:
            print(f"[WhiteBIT] processed={stats.processed} created={stats.created} updated={stats.updated} skipped={stats.skipped} disabled={stats.disabled}")

        return stats
