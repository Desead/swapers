from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Iterable, Optional, Tuple

from decimal import Decimal
from django.db import models, transaction

from app_market.models.exchange import Exchange, ExchangeKind
from app_market.models.exchange_asset import ExchangeAsset, AssetKind  # ← ДОБАВИЛ ExchangeAsset
from app_market.providers.base import UnifiedProviderBase, ProviderRow, AssetSyncStats
from app_market.providers.http import SESSION
from app_market.providers.numeric import (
    D, U, disp, json_safe,
    stable_set, memo_required_set,
    get_any_enabled_keys,
)

WB_BASE = "https://whitebit.com"
ASSETS_URL = f"{WB_BASE}/api/v4/public/assets"
FEE_URL = f"{WB_BASE}/api/v4/public/fee"
PRIV_FEE_PATH = "/api/v4/main-account/fee"
PRIV_FEE_URL = f"{WB_BASE}{PRIV_FEE_PATH}"


def _flex_percent(v: Any):
    if isinstance(v, dict):
        return D(v.get("percent"))
    return D(v)


class _FeeSide:
    __slots__ = ("min_amount", "max_amount", "fixed", "percent")

    def __init__(self, min_amount, max_amount, fixed, percent):
        self.min_amount = min_amount
        self.max_amount = max_amount
        self.fixed = fixed
        self.percent = percent


class _FeePack:
    __slots__ = ("deposit", "withdraw")

    def __init__(self, deposit: _FeeSide, withdraw: _FeeSide):
        self.deposit = deposit
        self.withdraw = withdraw


def _parse_public_fee(obj: dict) -> Dict[Tuple[str, Optional[str]], _FeePack]:
    """
    Ключи типа "USDT (TRC20)" | "BTC", значения с полями deposit/withdraw.
    Вернём карту {(ticker, network|None) -> _FeePack}
    """
    import re
    out: Dict[Tuple[str, Optional[str]], _FeePack] = {}
    for key, row in obj.items():
        if not isinstance(row, dict):
            continue
        m = re.match(r"^\s*([A-Za-z0-9]+)\s*(?:\(\s*([^)]+)\s*\))?\s*$", str(key))
        ticker = (m.group(1) if m else str(key)).strip().upper()
        network = (m.group(2).strip().upper() if (m and m.group(2)) else None)

        dep = row.get("deposit") or {}
        wd = row.get("withdraw") or {}

        out[(ticker, network)] = _FeePack(
            deposit=_FeeSide(
                min_amount=D(dep.get("min_amount")),
                max_amount=D(dep.get("max_amount")),
                fixed=D(dep.get("fixed")),
                percent=_flex_percent(dep.get("flex")),
            ),
            withdraw=_FeeSide(
                min_amount=D(wd.get("min_amount")),
                max_amount=D(wd.get("max_amount")),
                fixed=D(wd.get("fixed")),
                percent=_flex_percent(wd.get("flex")),
            ),
        )
    return out


def _fetch_private_fee(exchange: Exchange, *, timeout: int = 30) -> Dict[str, dict]:
    """
    Приватные комиссии возвращаются списком по тикерам (без сетей).
    Вернём карту {TICKER -> row}.
    """
    api_key, api_secret = get_any_enabled_keys(exchange)
    if not api_key or not api_secret:
        return {}

    body = {"request": PRIV_FEE_PATH, "nonce": int(time.time() * 1000)}
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    b64 = base64.b64encode(payload)
    sign = hmac.new(api_secret.encode("utf-8"), b64, hashlib.sha512).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-TXC-APIKEY": api_key,
        "X-TXC-PAYLOAD": b64.decode("ascii"),
        "X-TXC-SIGNATURE": sign,
    }

    resp = SESSION.post(PRIV_FEE_URL, headers=headers, data=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    out: Dict[str, dict] = {}
    if isinstance(data, list):
        for row in data:
            t = U(row.get("ticker"))
            if t:
                out[t] = row
    return out


def _merge_fee_for(ticker: str, network: Optional[str], pub: Dict[Tuple[str, Optional[str]], _FeePack], priv: Dict[str, dict]):
    """
    Возвращает (dep_pct, dep_fix, wd_pct, wd_fix).
    Приоритет: приватные по тикеру -> публичные по (ticker,net) -> публичные по (ticker,None) -> нули.
    """
    if ticker in priv:
        d = priv[ticker].get("deposit") or {}
        w = priv[ticker].get("withdraw") or {}
        return (
            D(d.get("percentFlex")), D(d.get("fixed")),
            D(w.get("percentFlex")), D(w.get("fixed")),
        )
    pack = pub.get((ticker, network)) or pub.get((ticker, None))
    if pack:
        return (
            pack.deposit.percent, pack.deposit.fixed,
            pack.withdraw.percent, pack.withdraw.fixed,
        )
    return (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))


class WhitebitAdapter(UnifiedProviderBase):
    """
    Универсальный адаптер WhiteBIT:

    Режим определяется автоматом:
      - Exchange.exchange_kind == CASH → работаем как «наличные»: берём только фиат, создаём один раз.
      - иначе (CEX) → работаем как «биржа»: берём только крипту (дефолт, чтобы не менять текущее поведение).

    Можно переопределить флаги явно: sync_assets(..., fiat=True/False, crypto=True/False).
    """
    code = "WHITEBIT"
    _exchange: Exchange | None = None
    _want_fiat: bool = False
    _want_crypto: bool = True
    _cash_mode: bool = False  # для пост-обработки (asset_kind, min_usdt, и т.п.)

    def provider_name_for_status(self) -> str:
        return "WhiteBIT"

    # ---- режим/флаги ----

    def _setup_mode(self, exchange: Exchange, fiat: Optional[bool], crypto: Optional[bool]) -> None:
        if fiat is None and crypto is None:
            # Автовыбор: CASH → только фиат, CEX → только крипта
            if exchange.exchange_kind == ExchangeKind.CASH:
                self._want_fiat, self._want_crypto = True, False
                self._cash_mode = True
            else:
                self._want_fiat, self._want_crypto = False, True
                self._cash_mode = False
        else:
            self._want_fiat = bool(fiat) if fiat is not None else False
            self._want_crypto = bool(crypto) if crypto is not None else False
            self._cash_mode = self._want_fiat and not self._want_crypto

    # ---- lifecycle ----

    def sync_assets(
        self,
        exchange: Exchange,
        *,
        timeout: int = 20,
        limit: int = 0,
        reconcile: bool = True,
        verbose: bool = False,
        fiat: Optional[bool] = None,
        crypto: Optional[bool] = None,
    ) -> AssetSyncStats:
        self._exchange = exchange
        self._setup_mode(exchange, fiat, crypto)

        # «один раз» для наличных
        if self._cash_mode and ExchangeAsset.objects.filter(exchange=exchange).exists():
            if verbose:
                print("[WHITEBIT] CASH уже инициализировано → пропуск")
            return AssetSyncStats()

        try:
            stats = super().sync_assets(exchange=exchange, timeout=timeout, limit=limit, reconcile=(reconcile and not self._cash_mode), verbose=verbose)
        finally:
            self._exchange = None

        # Пост-обработка для наличных: пометить как CASH и задать min в USDT = 1000, nominal=1
        if self._cash_mode and (stats.created or stats.updated or stats.skipped >= 0):
            with transaction.atomic():
                (ExchangeAsset.objects
                    .filter(exchange=exchange)
                    .update(
                        asset_kind=AssetKind.CASH,
                        nominal=1,
                        deposit_min_usdt=Decimal("1000"),
                        amount_precision_display=models.F("amount_precision"),
                    )
                 )
        return stats

    # ---- загрузка исходных данных ----

    def fetch_payload(self, *, timeout: int) -> dict:
        a = SESSION.get(ASSETS_URL, timeout=timeout); a.raise_for_status()
        f = SESSION.get(FEE_URL,    timeout=timeout); f.raise_for_status()

        priv_fee_map: Dict[str, dict] = {}
        if self._exchange is not None:
            try:
                priv_fee_map = _fetch_private_fee(self._exchange, timeout=timeout)
            except Exception:
                priv_fee_map = {}

        return {"assets": a.json(), "fee_pub": f.json(), "fee_priv": priv_fee_map}

    # ---- нормализация в ProviderRow ----

    def iter_rows(self, payload: dict) -> Iterable[ProviderRow]:
        stables = stable_set()
        memo_set = memo_required_set()

        assets_json = payload.get("assets") or {}
        fee_json = payload.get("fee_pub") or {}
        priv_fee_map = payload.get("fee_priv") or {}

        pub_fee_map = _parse_public_fee(fee_json)

        for ticker, meta in assets_json.items():
            if not isinstance(meta, dict):
                continue
            t = U(ticker)
            if not t:
                continue

            name = disp(meta.get("name")) or t
            precision = int(meta.get("currency_precision") or 8)

            providers = meta.get("providers") or {}
            confirmations = meta.get("confirmations", None)  # int или dict
            no_confirmations = (confirmations in (None, "", 0, {}))

            networks = meta.get("networks") or {}
            nets_dep = set(networks.get("deposits") or [])
            nets_wd = set(networks.get("withdraws") or [])
            lims = meta.get("limits") or {}
            lim_dep: dict = lims.get("deposit") or {}
            lim_wd: dict = lims.get("withdraw") or {}

            can_dep_global = bool(meta.get("can_deposit"))
            can_wd_global = bool(meta.get("can_withdraw"))
            requires_memo_flag = bool(meta.get("is_memo"))

            # --- FIAT ветка WhiteBIT ---
            # У WhiteBIT фиат отличается: есть providers и нет подтверждений.
            if providers and no_confirmations:
                if not self._want_fiat:
                    continue

                # CEX-режим (если вдруг явно разрешили fiat+crypto): сохраняем как есть (биржевой фиат)
                if not self._cash_mode:
                    dep_pct, dep_fix, wd_pct, wd_fix = _merge_fee_for(t, None, pub_fee_map, priv_fee_map)
                    dep_min = D(meta.get("min_deposit"))
                    dep_max = D(meta.get("max_deposit"))
                    wd_min = D(meta.get("min_withdraw"))
                    wd_max = D(meta.get("max_withdraw"))

                    yield ProviderRow(
                        asset_code=t,
                        asset_name=name,
                        chain_code="",
                        chain_name="",
                        AD=can_dep_global,
                        AW=can_wd_global,
                        conf_dep=0,
                        conf_wd=0,
                        dep_min=dep_min,
                        dep_max=dep_max,
                        wd_min=wd_min,
                        wd_max=wd_max,
                        dep_fee_pct=dep_pct,
                        dep_fee_fix=dep_fix,
                        wd_fee_pct=wd_pct,
                        wd_fee_fix=wd_fix,
                        requires_memo=False,
                        amount_precision=precision,
                        is_stable=(t in stables),
                        raw_meta={"assets": json_safe(meta)},
                    )
                    continue

                # CASH-режим: всегда разрешено (AD/AW=True), сеть пустая, точность 2, лимиты = 0 (min_usdt проставим постфактум)
                yield ProviderRow(
                    asset_code=t,
                    asset_name=name,
                    chain_code="",
                    chain_name="",
                    AD=True, AW=True,
                    conf_dep=0, conf_wd=0,
                    dep_min=D(0), dep_max=D(0),
                    wd_min=D(0), wd_max=D(0),
                    dep_fee_pct=D(0), dep_fee_fix=D(0),
                    wd_fee_pct=D(0), wd_fee_fix=D(0),
                    requires_memo=False,
                    amount_precision=2,
                    is_stable=(t in stables),
                    raw_meta={"assets": json_safe(meta), "mode": "CASH"},
                )
                continue

            # --- CRYPTO ветка ---
            if not self._want_crypto:
                continue

            confirms_map = confirmations if isinstance(confirmations, dict) else {}
            nets_all = sorted(
                set(nets_dep) | set(nets_wd) | set(confirms_map.keys()) | set((lim_dep or {}).keys()) | set((lim_wd or {}).keys())
            )

            # Без сетей — это скорее всего не поддерживаемый актив
            if not nets_all:
                yield ProviderRow(
                    asset_code=t,
                    asset_name=name,
                    chain_code="",
                    chain_name="",
                    AD=False, AW=False,
                    conf_dep=0, conf_wd=0,
                    dep_min=D(0), dep_max=D(0),
                    wd_min=D(0), wd_max=D(0),
                    dep_fee_pct=D(0), dep_fee_fix=D(0),
                    wd_fee_pct=D(0), wd_fee_fix=D(0),
                    requires_memo=False,
                    amount_precision=precision,
                    is_stable=(t in stables),
                    raw_meta={"assets": json_safe(meta)},
                )
                continue

            for net in nets_all:
                net_u = str(net).strip().upper()

                dep_ok = bool(can_dep_global and (not nets_dep or net in nets_dep))
                wd_ok  = bool(can_wd_global and (not nets_wd or net in nets_wd))

                conf = int((confirms_map or {}).get(net) or 0)

                dep_limits = (lim_dep.get(net) or {})
                wd_limits  = (lim_wd.get(net) or {})
                dep_min = D(dep_limits.get("min"))
                dep_max = D(dep_limits.get("max"))
                wd_min = D(wd_limits.get("min"))
                wd_max = D(wd_limits.get("max"))

                dep_pct, dep_fix, wd_pct, wd_fix = _merge_fee_for(t, net_u, pub_fee_map, priv_fee_map)
                requires_memo = bool(requires_memo_flag or (U(net_u) in memo_set))

                yield ProviderRow(
                    asset_code=t,
                    asset_name=name,
                    chain_code=net_u,
                    chain_name=net_u,
                    AD=dep_ok,
                    AW=wd_ok,
                    conf_dep=conf,
                    conf_wd=conf,
                    dep_min=dep_min,
                    dep_max=dep_max,
                    wd_min=wd_min,
                    wd_max=wd_max,
                    dep_fee_pct=dep_pct,
                    dep_fee_fix=dep_fix,
                    wd_fee_pct=wd_pct,
                    wd_fee_fix=wd_fix,
                    requires_memo=requires_memo,
                    amount_precision=precision,
                    is_stable=(t in stables),
                    raw_meta={"assets": json_safe(meta)},
                )
