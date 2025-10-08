from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Set, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from django.db import transaction
from django.utils import timezone

from app_market.models.exchange import Exchange
from app_market.models.exchange_asset import ExchangeAsset, AssetKind
from .base import ProviderAdapter, AssetSyncStats
from .numeric import (
    UA, D, to_db_amount, to_db_percent, json_safe,
    U, disp, B,
    stable_set, memo_required_set,
    get_any_enabled_keys, infer_asset_kind, crypto_withdraw_guard,
)

WB_BASE = "https://whitebit.com"
ASSETS_URL = f"{WB_BASE}/api/v4/public/assets"
FEE_URL = f"{WB_BASE}/api/v4/public/fee"
PRIV_FEE_PATH = "/api/v4/main-account/fee"
PRIV_FEE_URL = f"{WB_BASE}{PRIV_FEE_PATH}"


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
        return D(v.get("percent"))
    return D(v)


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
                min_amount=D(dep.get("min_amount")),
                max_amount=D(dep.get("max_amount")),
                fixed=D(dep.get("fixed")),
                percent=_flex_percent(dep.get("flex")),
            ),
            withdraw=FeeSide(
                min_amount=D(wd.get("min_amount")),
                max_amount=D(wd.get("max_amount")),
                fixed=D(wd.get("fixed")),
                percent=_flex_percent(wd.get("flex")),
            ),
        )
    return out


def _parse_public_assets(obj: dict) -> Dict[Tuple[str, Optional[str]], dict]:
    result: Dict[Tuple[str, Optional[str]], dict] = {}
    for ticker, payload in obj.items():
        if not isinstance(payload, dict):
            continue
        t = U(ticker)
        name = disp(payload.get("name")) or t
        precision = int(payload.get("currency_precision") or 8)
        requires_memo = B(payload.get("is_memo"))
        can_dep_global = B(payload.get("can_deposit"))
        can_wd_global = B(payload.get("can_withdraw"))

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
                "deposit_limits": {"min": D(payload.get("min_deposit")), "max": D(payload.get("max_deposit"))},
                "withdraw_limits": {"min": D(payload.get("min_withdraw")), "max": D(payload.get("max_withdraw"))},
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
                    "min": D((lim_dep.get(net) or {}).get("min")),
                    "max": D((lim_dep.get(net) or {}).get("max")),
                },
                "withdraw_limits": {
                    "min": D((lim_wd.get(net) or {}).get("min")),
                    "max": D((lim_wd.get(net) or {}).get("max")),
                },
            }
    return result


# === Ключи ===

def _fetch_private_fee(api_key: str, api_secret: str, timeout: int = 30) -> Dict[str, dict]:
    body = {"request": PRIV_FEE_PATH, "nonce": int(time.time() * 1000)}
    data = _http_post_signed_json(PRIV_FEE_URL, body, api_key, api_secret, timeout=timeout)
    out: Dict[str, dict] = {}
    if isinstance(data, list):
        for row in data:
            t = U(row.get("ticker"))
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
        stables = stable_set()
        memo_set = memo_required_set()

        # публичные структуры
        assets_json = _http_get_json(ASSETS_URL, timeout=timeout)
        fee_json = _http_get_json(FEE_URL, timeout=timeout)

        assets_map = _parse_public_assets(assets_json)
        pub_fee_map = _parse_public_fee(fee_json)

        # приватные комиссии (приоритетнее)
        api_key, api_secret = get_any_enabled_keys(exchange)
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
                    D(d.get("percentFlex")), D(d.get("fixed")),
                    D(w.get("percentFlex")), D(w.get("fixed")),
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

            dep_conf = int(meta.get("confirmations") or 0)
            kind_guess = meta.get("asset_kind") or AssetKind.CRYPTO
            if kind_guess == AssetKind.CRYPTO and dep_conf < 1:
                dep_conf = 1
            wd_conf = dep_conf  # отдельного нет — берём минимум как dep_conf

            dep_lim = meta.get("deposit_limits") or {}
            wd_lim = meta.get("withdraw_limits") or {}

            dep_pct, dep_fix, wd_pct, wd_fix = merge_fee(ticker, network)

            provider_memo = bool(meta.get("requires_memo") or False)
            chain_norm = U(network or ticker)
            requires_memo = (kind_guess == AssetKind.CRYPTO) and (provider_memo or (chain_norm in memo_set))

            rows.append(_Row(
                ticker=ticker,
                chain=network,
                name=disp(meta.get("asset_name")) or ticker,
                kind=kind_guess,
                AD=B(meta.get("can_deposit")),
                AW=B(meta.get("can_withdraw")),
                conf_dep=dep_conf,
                conf_wd=wd_conf,
                dep_min=D(dep_lim.get("min")),
                dep_max=D(dep_lim.get("max")),
                wd_min=D(wd_lim.get("min")),
                wd_max=D(wd_lim.get("max")),
                dep_fee_pct=dep_pct,
                dep_fee_fix=dep_fix,
                wd_fee_pct=wd_pct,
                wd_fee_fix=wd_fix,
                requires_memo=requires_memo,
                amount_precision=int(meta.get("amount_precision") or 8),
                raw_meta={"assets": json_safe(meta)},
                is_stable=(kind_guess == AssetKind.CRYPTO) and (ticker in stables),
            ))

        # UPSERT + reconcile
        seen: Set[Tuple[str, str]] = set()

        for r in rows:
            stats.processed += 1
            chain_code = (r.chain or r.ticker)

            # Определяем тип актива единообразно и применяем централизованные лимиты для крипты
            kind = infer_asset_kind(r.ticker, chain_code, chain_code)
            prec = int(r.amount_precision or 8)

            if kind == AssetKind.CRYPTO:
                ok, wd_min_q, wd_fee_fix_q = crypto_withdraw_guard(r.wd_min, r.wd_fee_fix, prec)
                if not ok:
                    stats.skipped += 1
                    continue
            else:
                wd_min_q = to_db_amount(r.wd_min, prec)
                wd_fee_fix_q = to_db_amount(r.wd_fee_fix, prec)

            # прошла проверки — считаем увиденной
            seen.add((r.ticker, chain_code))

            new_vals = dict(
                asset_name=r.name,
                AD=bool(r.AD),
                AW=bool(r.AW),
                confirmations_deposit=int(r.conf_dep if (kind == AssetKind.FIAT) or (r.conf_dep > 0) else 1),
                confirmations_withdraw=int(max(r.conf_dep if r.conf_dep > 0 else 1, r.conf_wd)),

                deposit_fee_percent=to_db_percent(r.dep_fee_pct),
                deposit_fee_fixed=to_db_amount(r.dep_fee_fix, prec),
                deposit_min=to_db_amount(r.dep_min, prec),
                deposit_max=to_db_amount(r.dep_max, prec),
                # deposit_min_usdt — не трогаем
                # deposit_max_usdt — не трогаем

                withdraw_fee_percent=to_db_percent(r.wd_fee_pct),
                withdraw_fee_fixed=wd_fee_fix_q,
                withdraw_min=wd_min_q,
                withdraw_max=to_db_amount(r.wd_max, prec),
                # withdraw_min_usdt — не трогаем
                # withdraw_max_usdt — не трогаем

                requires_memo=bool(r.requires_memo),
                is_stablecoin=bool(r.is_stable),
                amount_precision=prec,
                asset_kind=kind,
                provider_symbol=r.ticker,
                provider_chain=(r.chain or ""),
            )

            obj, created = ExchangeAsset.objects.get_or_create(
                exchange=exchange,
                asset_code=r.ticker,
                chain_code=chain_code,
                defaults={**new_vals, "raw_metadata": json_safe(r.raw_meta), "chain_name": chain_code},
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
                    obj.raw_metadata = json_safe(r.raw_meta)
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
