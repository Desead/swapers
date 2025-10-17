from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from app_main.models import SiteSetup

import os
from django.db import transaction

from app_market.models.exchange import Exchange
from app_market.models.exchange_asset import ExchangeAsset, AssetKind
from app_market.providers.base import UnifiedProviderBase, ProviderRow
from app_market.providers.http import SESSION
from app_market.providers.numeric import (
    D, U, B, disp, stable_set, get_any_enabled_keys, crypto_withdraw_guard
)

WB_BASE = "https://whitebit.com"
ASSETS_URL = f"{WB_BASE}/api/v4/public/assets"
FEE_URL = f"{WB_BASE}/api/v4/public/fee"
PRIV_FEE_PATH = "/api/v4/main-account/fee"
PRIV_FEE_URL = f"{WB_BASE}{PRIV_FEE_PATH}"

# цепи, которыми в БД помечаются «безсетевые» активы (фиат)
CASH_CHAIN_MARKERS = ("FIAT", "NOCHAIN", "NoChain", "")


# ---------- helpers ----------

def _flex_percent(v: Any) -> Decimal:
    if isinstance(v, dict):
        return D(v.get("percent"))
    return D(v)


def _get_stables_from_site_setup() -> Set[str]:
    """
    Пробуем вытащить список стейблкоинов из SiteSetup.stablecoins.
    Если модель недоступна в проекте — fallback на numeric.stable_set().
    """
    try:
        raw = (SiteSetup.get_solo().stablecoins or "").strip()
        if not raw:
            return set()
        import re
        toks = [t.strip().upper() for t in re.split(r"[\s,;]+", raw) if t.strip()]
        return set(toks)
    except Exception:
        try:
            return set(stable_set())
        except Exception:
            return set()


class _FeeSide:
    __slots__ = ("min_amount", "max_amount", "fixed", "percent")

    def __init__(self, min_amount, max_amount, fixed, percent):
        self.min_amount = D(min_amount)
        self.max_amount = D(max_amount)
        self.fixed = D(fixed)
        self.percent = _flex_percent(percent)


class _FeePack:
    __slots__ = ("deposit", "withdraw")

    def __init__(self, deposit: _FeeSide, withdraw: _FeeSide):
        self.deposit = deposit
        self.withdraw = withdraw


def _parse_public_fee(obj: dict) -> Dict[Tuple[str, Optional[str]], _FeePack]:
    """
    Публичные комиссии: ключи вида "USDT (TRC20)" или "BTC".
    Вернём карту {(ticker, network|None) -> _FeePack}.
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
                min_amount=dep.get("min_amount"),
                max_amount=dep.get("max_amount"),
                fixed=dep.get("fixed"),
                percent=dep.get("flex"),
            ),
            withdraw=_FeeSide(
                min_amount=wd.get("min_amount"),
                max_amount=wd.get("max_amount"),
                fixed=wd.get("fixed"),
                percent=wd.get("flex"),
            ),
        )
    return out


def _fetch_private_fee(exchange: Exchange, *, timeout: int = 30) -> Dict[str, dict]:
    """
    Приватный эндпоинт возвращает список по тикерам (без сетей).
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


# ---------- adapter ----------

class WhitebitAdapter(UnifiedProviderBase):
    """
    Единый адаптер WhiteBIT:
      • Fiat = есть ключ 'providers' (даже пустой) → это «наличные»; крипта — иначе.
      • Крипта: сети берём из networks (строка / список / dict с deposits/withdraws / dict с ключами-сетями),
        при их отсутствии — из confirmations (dict). Если всё пусто — fallback: [ticker].
      • D/W open считаем только по явным спискам deposits/withdraws (если их нет — False/False).
      • Комиссии: приватные (если есть ключи) имеют приоритет, публичные — fallback; на фиат не применяем.
      • После upsert помечаем «наличные» как CASH (nominal=1, precision_display=2, min_usdt=1000).
      • Стейблкоины для крипты берём из SiteSetup.stablecoins (fallback — numeric.stable_set()).
    """

    code = "WHITEBIT"
    label = "WhiteBIT"

    def __init__(self) -> None:
        super().__init__()
        self._fiat_seen: Set[str] = set()             # asset_code-ы, распознанные как «наличные»
        self._guard_skips: List[Tuple[str, str]] = [] # для отладки пропусков wd_guard: (asset@net)

    def fetch_payload(self, *, timeout: int = 20) -> Dict[str, Any]:
        # assets
        r_assets = SESSION.get(ASSETS_URL, timeout=timeout)
        r_assets.raise_for_status()
        assets = r_assets.json()
        if not isinstance(assets, dict):
            assets = {}

        # fees (public)
        r_fee = SESSION.get(FEE_URL, timeout=timeout)
        r_fee.raise_for_status()
        fee_pub_json = r_fee.json()
        pub_map = _parse_public_fee(fee_pub_json if isinstance(fee_pub_json, dict) else {})

        # stables из SiteSetup (или fallback)
        stables = _get_stables_from_site_setup()

        return {"assets": assets, "fee_pub": pub_map, "stables": stables}

    def _collect_networks(self, meta: dict) -> Tuple[List[str], Set[str], Set[str], dict]:
        """
        Возвращает (nets_all, nets_dep, nets_wd, conf_map)
        - networks может быть: строкой / списком / dict с deposits/withdraws / dict с ключами-сетями
        - если deposits/withdraws отсутствуют → dep/wd закрыты (пустые множества)
        - если всё пусто → берём ключи из confirmations (dict)
        """
        networks = meta.get("networks")
        conf_map = meta.get("confirmations") or {}
        nets_dep: Set[str] = set()
        nets_wd: Set[str] = set()
        nets_all: Set[str] = set()

        if isinstance(networks, str):
            nets_all.add(U(networks))
        elif isinstance(networks, list):
            for n in networks:
                nets_all.add(U(n))
        elif isinstance(networks, dict) and ("deposits" in networks or "withdraws" in networks):
            for n in (networks.get("deposits") or []):
                n_u = U(n); nets_all.add(n_u); nets_dep.add(n_u)
            for n in (networks.get("withdraws") or []):
                n_u = U(n); nets_all.add(n_u); nets_wd.add(n_u)
        elif isinstance(networks, dict):
            # предположим формат {"ERC20": {...}, "TRC20": {...}}
            for n in networks.keys():
                nets_all.add(U(n))

        if not nets_all and isinstance(conf_map, dict):
            for n in conf_map.keys():
                nets_all.add(U(n))

        return (sorted(nets_all), nets_dep, nets_wd, conf_map if isinstance(conf_map, dict) else {})

    def iter_rows(self, payload: Dict[str, Any]) -> Iterable[ProviderRow]:
        self._fiat_seen.clear()
        self._guard_skips.clear()

        assets_json = payload.get("assets") or {}
        pub_map: Dict[Tuple[str, Optional[str]], _FeePack] = payload.get("fee_pub") or {}
        stables: Set[str] = payload.get("stables") or set()

        for ticker, meta in assets_json.items():
            tkr = U(ticker)
            if not tkr:
                continue

            name = disp(meta.get("name")) or tkr

            # ---- НАЛИЧНЫЕ (fiat) ----
            # Главное правило: есть ключ 'providers' → это фиат (наличные)
            if "providers" in meta:
                self._fiat_seen.add(tkr)
                yield ProviderRow(
                    asset_code=tkr,
                    asset_name=name,
                    chain_code="",      # без сети → base сохранит как «FIAT/NoChain»
                    chain_name="",
                    AD=True, AW=True,
                    conf_dep=0, conf_wd=0,
                    dep_min=D(0), dep_max=D(0),
                    wd_min=D(0), wd_max=D(0),
                    dep_fee_pct=D(0), dep_fee_fix=D(0),
                    wd_fee_pct=D(0), wd_fee_fix=D(0),
                    requires_memo=False,
                    amount_precision=2,
                    is_stable=False,     # фиат никогда не стейблкоин
                    raw_meta=meta,
                )
                continue

            # ---- КРИПТА ----
            can_dep_root = B(meta.get("can_deposit"))
            can_wd_root = B(meta.get("can_withdraw"))
            memo_req = B(meta.get("is_memo"))
            prec = int(meta.get("currency_precision") or 8)

            nets_all, nets_dep, nets_wd, conf_map = self._collect_networks(meta)
            if not nets_all:
                nets_all = [tkr]  # fallback название сети

            for net in nets_all:
                # D/W открыто только если списки есть и сеть в них присутствует
                dep_open = (len(nets_dep) > 0 and net in nets_dep) and can_dep_root
                wd_open  = (len(nets_wd) > 0 and net in nets_wd) and can_wd_root

                limits = meta.get("limits") or {}
                dep_limits = (limits.get("deposit") or {}).get(net) or {}
                wd_limits  = (limits.get("withdraw") or {}).get(net) or {}

                dep_min = D(dep_limits.get("min") or 0)
                dep_max = D(dep_limits.get("max") or 0)
                wd_min = D(wd_limits.get("min") or 0)
                wd_max = D(wd_limits.get("max") or 0)

                conf = int((conf_map or {}).get(net) or 0)

                dep_pct, dep_fix, wd_pct, wd_fix = (D(0), D(0), D(0), D(0))
                pack = pub_map.get((tkr, net)) or pub_map.get((tkr, None))
                if pack:
                    dep_pct, dep_fix = pack.deposit.percent, pack.deposit.fixed
                    wd_pct, wd_fix = pack.withdraw.percent, pack.withdraw.fixed

                # DEBUG: кандидаты на пропуск guard (совпадает с базовой логикой)
                ok, _, _ = crypto_withdraw_guard(wd_min, wd_fix, prec)
                if not ok:
                    self._guard_skips.append((tkr, net or ""))

                yield ProviderRow(
                    asset_code=tkr,
                    asset_name=name,
                    chain_code=U(net),
                    chain_name=U(net),
                    AD=dep_open,
                    AW=wd_open,
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
                    requires_memo=memo_req,
                    amount_precision=prec,
                    is_stable=(tkr in stables),   # <= стейблы из SiteSetup
                    raw_meta=meta,
                )

    def sync_assets(
        self,
        exchange: Exchange,
        *,
        timeout: int = 20,
        limit: int = 0,
        reconcile: bool = True,
        verbose: bool = False,
    ):
        # 1) обычный конвейер
        stats = super().sync_assets(
            exchange=exchange,
            timeout=timeout,
            limit=limit,
            reconcile=reconcile,
            verbose=verbose,
        )

        # 2) приватные комиссии (не применяем к наличным)
        try:
            priv_map = _fetch_private_fee(exchange, timeout=timeout)
        except Exception:
            priv_map = {}

        if priv_map:
            with transaction.atomic():
                for tkr, row in priv_map.items():
                    d = row.get("deposit") or {}
                    w = row.get("withdraw") or {}
                    dep_pct = D(d.get("percentFlex"))
                    dep_fix = D(d.get("fixed"))
                    wd_pct  = D(w.get("percentFlex"))
                    wd_fix  = D(w.get("fixed"))
                    (ExchangeAsset.objects
                        .filter(exchange=exchange, asset_code=tkr)
                        .exclude(chain_code__in=CASH_CHAIN_MARKERS)
                        .update(
                            deposit_fee_percent=dep_pct,
                            deposit_fee_fixed=dep_fix,
                            withdraw_fee_percent=wd_pct,
                            withdraw_fee_fixed=wd_fix,
                        ))

        # 3) явно отметить «наличные» корректным типом и базовыми атрибутами
        if self._fiat_seen:
            with transaction.atomic():
                (ExchangeAsset.objects
                 .filter(exchange=exchange, asset_code__in=list(self._fiat_seen))
                 .filter(chain_code__in=CASH_CHAIN_MARKERS)
                 .update(
                     asset_kind=AssetKind.CASH,
                     nominal=Decimal("1"),
                     amount_precision_display=2,
                     deposit_min_usdt=Decimal("1000"),
                     withdraw_min_usdt=Decimal("1000"),     # ← добавили мин. вывод в USDT
                     AD=True, AW=True,
                     confirmations_deposit=0,
                     confirmations_withdraw=0,
                 ))

        return stats
