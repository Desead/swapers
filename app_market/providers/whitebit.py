from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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


def _http_get_json(url: str, timeout: int = 20) -> Any:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def _http_post_signed_json(url: str, body: dict, api_key: str, api_secret: str, timeout: int = 30) -> Any:
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    b64 = base64.b64encode(payload)
    sign = hmac.new(api_secret.encode("utf-8"), b64, hashlib.sha512).hexdigest()
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


def _D(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if x in (None, "", "0E-10"):
        return Decimal("0")
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _B(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    if isinstance(x, str):
        v = x.strip().lower()
        return v in {"1", "true", "yes", "y", "on"}
    return False


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


def _json_safe(o: Any) -> Any:
    """
    Рекурсивно делает объект JSON-сериализуемым:
    - Decimal -> str
    - dict/list -> обходит внутренности
    """
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return o


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
    """
    Возвращает карту (ticker, network_or_None) -> meta
    ВНИМАНИЕ: внутри meta есть Decimal — их нельзя напрямую класть в JSONField!
    Поэтому при сохранении raw_metadata всегда используем _json_safe(meta).
    """
    result: Dict[Tuple[str, Optional[str]], dict] = {}
    for ticker, payload in obj.items():
        if not isinstance(payload, dict):
            continue
        t = str(ticker).strip().upper()
        name = (payload.get("name") or "").strip()
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


def _fetch_private_fee(api_key: str, api_secret: str, timeout: int = 30) -> Dict[str, dict]:
    body = {"request": PRIV_FEE_PATH, "nonce": int(time.time() * 1000)}
    data = _http_post_signed_json(PRIV_FEE_URL, body, api_key, api_secret, timeout=timeout)
    out: Dict[str, dict] = {}
    if isinstance(data, list):
        for row in data:
            t = str(row.get("ticker") or "").strip().upper()
            if t:
                out[t] = row
    return out


def _fee_from_private(ticker: str, priv: Dict[str, dict]) -> Optional[FeePack]:
    row = priv.get(ticker)
    if not row:
        return None
    dep = row.get("deposit") or {}
    wd = row.get("withdraw") or {}
    return FeePack(
        deposit=FeeSide(
            min_amount=_D(dep.get("minAmount")),
            max_amount=_D(dep.get("maxAmount")),
            fixed=_D(dep.get("fixed")),
            percent=_D(dep.get("percentFlex")),
        ),
        withdraw=FeeSide(
            min_amount=_D(wd.get("minAmount")),
            max_amount=_D(wd.get("maxAmount")),
            fixed=_D(wd.get("fixed")),
            percent=_D(wd.get("percentFlex")),
        ),
    )


def _merge_fee(pub_fee: Dict[Tuple[str, Optional[str]], FeePack],
               priv_fee: Dict[str, dict],
               ticker: str,
               network: Optional[str]) -> FeePack:
    f_priv = _fee_from_private(ticker, priv_fee) if priv_fee else None
    f_pub_net = pub_fee.get((ticker, network))
    f_pub_tic = pub_fee.get((ticker, None))

    def pick(getter):
        if f_priv:
            return getter(f_priv)
        if f_pub_net:
            return getter(f_pub_net)
        if f_pub_tic:
            return getter(f_pub_tic)
        return FeeSide()

    dep = pick(lambda p: p.deposit)
    wd = pick(lambda p: p.withdraw)
    return FeePack(deposit=dep, withdraw=wd)


def _fee_to_dict(f: FeePack) -> dict:
    return {
        "deposit": {
            "min_amount": str(f.deposit.min_amount),
            "max_amount": str(f.deposit.max_amount),
            "fixed": str(f.deposit.fixed),
            "percent": str(f.deposit.percent),
        },
        "withdraw": {
            "min_amount": str(f.withdraw.min_amount),
            "max_amount": str(f.withdraw.max_amount),
            "fixed": str(f.withdraw.fixed),
            "percent": str(f.withdraw.percent),
        },
    }


def _get_any_enabled_keys(exchange: Exchange) -> tuple[Optional[str], Optional[str]]:
    key = (
        ExchangeApiKey.objects
        .filter(exchange=exchange, is_enabled=True)
        .order_by("id")
        .first()
    )
    return ((key.api_key or None), (key.api_secret or None)) if key else (None, None)


class WhitebitAdapter:
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

        try:
            assets_json = _http_get_json(ASSETS_URL, timeout=timeout)
            fee_json = _http_get_json(FEE_URL, timeout=timeout)
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            raise RuntimeError(f"WhiteBIT: ошибка запросов: {e}")

        assets_map = _parse_public_assets(assets_json)
        pub_fee_map = _parse_public_fee(fee_json)

        api_key, api_secret = _get_any_enabled_keys(exchange)
        priv_fee_map: Dict[str, dict] = {}
        if api_key and api_secret:
            try:
                priv_fee_map = _fetch_private_fee(api_key, api_secret, timeout=timeout)
            except Exception:
                if verbose:
                    print("[WhiteBIT] приватные комиссии не получены, работаем по публичным")

        processed_keys: Set[Tuple[str, str]] = set()

        for i, ((ticker, network), meta) in enumerate(assets_map.items(), start=1):
            if limit and i > limit:
                break
            stats.processed += 1

            chain_code = (network or ticker)
            chain_norm = (chain_code or "").strip().upper()
            processed_keys.add((ticker, chain_code))

            kind: str = meta.get("asset_kind") or AssetKind.CRYPTO

            AD = _B(meta.get("can_deposit"))
            AW = _B(meta.get("can_withdraw"))

            dep_conf = int(meta.get("confirmations") or 0)
            if kind == AssetKind.CRYPTO and dep_conf < 1:
                dep_conf = 1
            wdr_conf = dep_conf

            dep_lim = meta.get("deposit_limits") or {}
            wd_lim = meta.get("withdraw_limits") or {}

            fees = _merge_fee(pub_fee_map, priv_fee_map, ticker, network)

            # requires_memo: приоритет SiteSetup для крипты; иначе — провайдер; фиат — False
            provider_memo = bool(meta.get("requires_memo") or False)
            site_enforces_memo = (kind == AssetKind.CRYPTO) and (chain_norm in memo_set)
            requires_memo = (kind == AssetKind.CRYPTO) and (site_enforces_memo or provider_memo)
            memo_source = "site_setup" if site_enforces_memo else ("provider" if provider_memo else "none")

            raw_meta = {
                "assets": _json_safe(meta),     # ВАЖНО: убираем Decimal из meta
                "fees": _fee_to_dict(fees),     # Decimal -> str
                "memo": {"effective": requires_memo, "source": memo_source, "chain": chain_norm},
                "source": "whitebit",
                "synced_at": timezone.now().isoformat(),
            }

            defaults = dict(
                asset_name=(meta.get("asset_name") or ""),
                amount_precision=int(meta.get("amount_precision") or 8),
                requires_memo=requires_memo,
                asset_kind=kind,
                provider_symbol=ticker,
                provider_chain=(network or ""),
                AD=AD, AW=AW,
                confirmations_deposit=dep_conf,
                confirmations_withdraw=max(dep_conf, wdr_conf),
                deposit_min=_D(dep_lim.get("min")),
                deposit_max=_D(dep_lim.get("max")),
                withdraw_min=_D(wd_lim.get("min")),
                withdraw_max=_D(wd_lim.get("max")),
                deposit_fee_fixed=fees.deposit.fixed,
                deposit_fee_percent=fees.deposit.percent,
                withdraw_fee_fixed=fees.withdraw.fixed,
                withdraw_fee_percent=fees.withdraw.percent,
                is_stablecoin=(kind == AssetKind.CRYPTO) and (
                    ticker.upper() in stable_set or (meta.get("asset_name") or "").strip().upper() in stable_set
                ),
                raw_metadata=raw_meta,
                last_synced_at=timezone.now(),
            )

            obj, created = ExchangeAsset.objects.get_or_create(
                exchange=exchange,
                asset_code=ticker,
                chain_code=chain_code,
                defaults=defaults,
            )

            if created:
                stats.created += 1
            else:
                changed = False
                for field, val in defaults.items():
                    if getattr(obj, field) != val:
                        setattr(obj, field, val)
                        changed = True
                if changed:
                    obj.updated_at = timezone.now()
                    obj.save(update_fields=list(defaults.keys()) + ["updated_at"])
                    stats.updated += 1
                else:
                    stats.skipped += 1

        if reconcile:
            for obj in ExchangeAsset.objects.filter(exchange=exchange).only("id", "asset_code", "chain_code", "AD", "AW"):
                key = (obj.asset_code, obj.chain_code)
                if key not in processed_keys and (obj.AD or obj.AW):
                    ExchangeAsset.objects.filter(pk=obj.pk).update(
                        AD=False, AW=False,
                        status_note="Отключено: отсутствует в текущей выдаче провайдера",
                        updated_at=timezone.now(),
                    )
                    stats.disabled += 1

        return stats
