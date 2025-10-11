from __future__ import annotations

import hmac
import hashlib
import time
from typing import Any, Iterable, List
from urllib.parse import urlencode

import requests
from django.conf import settings

from app_market.models.exchange import Exchange
from app_market.providers.base import UnifiedProviderBase, ProviderRow
from app_market.providers.http import SESSION
from app_market.providers.numeric import (
    D, U, B, disp, json_safe,
    stable_set, memo_required_set,
    get_any_enabled_keys,
)

BASE = "https://api.mexc.com"
CAPITAL_CONFIG_URL = "/api/v3/capital/config/getall"
RECV_WINDOW = int(getattr(settings, "MEXC_RECV_WINDOW", 20000))  # мс


def _mexc_sign(secret: str, query: str) -> str:
    return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()


def _unwrap(payload: Any) -> List[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "result", "rows"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
        code = payload.get("code")
        msg = payload.get("msg") or payload.get("message") or ""
        if code not in (None, 0, "0", 200, "200"):
            raise requests.HTTPError(f"MEXC API error: code={code} msg={msg}")
        return []
    return []


class MexcAdapter(UnifiedProviderBase):
    code = "MEXC"
    _exchange: Exchange | None = None

    def provider_name_for_status(self) -> str:
        return "MEXC"

    def policy_write_withdraw_max(self) -> bool:
        # Для MEXC их цифры по withdrawMax часто «мусорные» — не пишем
        return False

    def sync_assets(
        self, exchange: Exchange, *, timeout: int = 20, limit: int = 0, reconcile: bool = True, verbose: bool = False
    ):
        self._exchange = exchange
        try:
            return super().sync_assets(exchange=exchange, timeout=timeout, limit=limit, reconcile=reconcile, verbose=verbose)
        finally:
            self._exchange = None

    def fetch_payload(self, *, timeout: int) -> list[dict]:
        if not self._exchange:
            raise RuntimeError("MEXC: не назначена биржа для адаптера")
        api_key, api_secret = get_any_enabled_keys(self._exchange)
        if not api_key or not api_secret:
            raise RuntimeError("MEXC: не найдены активные API-ключи")

        ts = int(time.time() * 1000)
        params = {"timestamp": ts, "recvWindow": RECV_WINDOW}
        qs = urlencode(params)  # подписываем БЕЗ signature
        sig = _mexc_sign(api_secret, qs)
        params["signature"] = sig

        headers = {"X-MEXC-APIKEY": api_key}

        resp = SESSION.get(BASE + CAPITAL_CONFIG_URL, headers=headers, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return _unwrap(data)

    def iter_rows(self, payload: list[dict]) -> Iterable[ProviderRow]:
        stables = stable_set()
        memo_chains = memo_required_set()

        for entry in payload:
            if not isinstance(entry, dict):
                continue

            root = entry.get("coin") if isinstance(entry.get("coin"), dict) else entry
            sym = U(root.get("coin") or root.get("asset"))
            if not sym:
                continue
            asset_name = disp(root.get("name") or root.get("fullName") or sym)

            networks = root.get("networkList") or root.get("chains") or []
            if not isinstance(networks, list) or len(networks) == 0:
                yield ProviderRow(
                    asset_code=sym,
                    asset_name=asset_name,
                    chain_code="",
                    chain_name="",
                    AD=False, AW=False,
                    conf_dep=0, conf_wd=0,
                    dep_min=D(0), dep_max=D(0),
                    wd_min=D(0), wd_max=D(0),
                    dep_fee_pct=D(0), dep_fee_fix=D(0),
                    wd_fee_pct=D(0), wd_fee_fix=D(0),
                    requires_memo=False,
                    amount_precision=8,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    raw_meta={"coin": json_safe(root)},
                )
                continue

            for net in networks:
                if not isinstance(net, dict):
                    continue
                chain_code = U(net.get("network") or net.get("netWork") or net.get("chain") or net.get("name"))
                if not chain_code:
                    continue
                chain_name = disp(net.get("name") or net.get("network") or chain_code)

                api_dep_on = B(net.get("depositEnable"), net.get("canDeposit"))
                api_wd_on  = B(net.get("withdrawEnable"), net.get("canWithdraw"))

                dep_conf = int((net.get("minConfirm") or net.get("confirmTimes") or 0) or 0)
                wd_conf  = int((net.get("withdrawConfirm") or net.get("withdrawConfirmTimes") or dep_conf) or 0)

                dep_min = D(net.get("depositMin"))
                dep_max = D(net.get("depositMax"))
                wd_min  = D(net.get("withdrawMin"))
                wd_max  = D(net.get("withdrawMax"))

                wd_fee_fix = D(net.get("withdrawFee"))
                wd_fee_pct = D(net.get("withdrawFeePercent") or 0)
                dep_fee_fix = D(net.get("depositFee") or net.get("depositFeeFixed") or 0)
                dep_fee_pct = D(net.get("depositFeePercent") or 0)

                requires_memo = B(net.get("needTag"))
                if not requires_memo:
                    tips = (disp(net.get("specialTips") or "")).lower()
                    if "memo" in tips or "tag" in tips:
                        requires_memo = True
                if not requires_memo and (chain_code in memo_chains or U(chain_name) in memo_chains):
                    requires_memo = True

                amount_precision = int((net.get("withdrawPrecision") or net.get("accuracy") or 8) or 8)

                yield ProviderRow(
                    asset_code=sym,
                    asset_name=asset_name,
                    chain_code=chain_code,
                    chain_name=chain_name,
                    AD=api_dep_on,
                    AW=api_wd_on,
                    conf_dep=dep_conf,
                    conf_wd=wd_conf,
                    dep_min=dep_min,
                    dep_max=dep_max,
                    wd_min=wd_min,
                    wd_max=wd_max,
                    dep_fee_pct=dep_fee_pct,
                    dep_fee_fix=dep_fee_fix,
                    wd_fee_pct=wd_fee_pct,
                    wd_fee_fix=wd_fee_fix,
                    requires_memo=requires_memo,
                    amount_precision=amount_precision,
                    is_stable=(sym in stables) or (U(asset_name) in stables),
                    raw_meta={"coin": json_safe(root)},
                )
