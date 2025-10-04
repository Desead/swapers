from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Tuple

import requests
from django.apps import apps
from django.db import transaction
from django.utils import timezone

from .base import ProviderAdapter  # тот же базовый класс, что и у Whitebit/Kucoin/Bybit
from app_market.models.exchange import LiquidityProvider

# Модели
Exchange = apps.get_model("app_market", "Exchange")
ExchangeAsset = apps.get_model("app_market", "ExchangeAsset")
ExchangeApiKey = apps.get_model("app_market", "ExchangeApiKey")
try:
    CurrencyMap = apps.get_model("app_market", "CurrencyMap")
except Exception:
    CurrencyMap = None  # если маппинга пока нет — пропустим

# SiteSetup (singleton со списками стейблов и сетей с memo)
SiteSetup = apps.get_model("app_main", "SiteSetup")

UA = "swapers-sync/1.0 (+https://github.com/Desead/swapers)"
_HTX_HOST = "api.huobi.pro"


# ---------- утилиты ----------

def _now_utc_iso() -> str:
    # Формат, который HTX использует для подписи (UTC без микросекунд)
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _as_dec(x: Any, default: Decimal = Decimal("0")) -> Decimal:
    if x is None or x == "":
        return default
    try:
        return Decimal(str(x))
    except Exception:
        return default


def _as_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _bool(x: Any, default: bool = False) -> bool:
    if isinstance(x, bool):
        return x
    if x is None:
        return default
    s = str(x).strip().lower()
    if s in {"1", "true", "yes", "y", "enabled", "enable", "on", "allowed"}:
        return True
    if s in {"0", "false", "no", "n", "disabled", "off", "forbidden"}:
        return False
    return default


def _upper_clean(s: Any) -> str:
    return (str(s or "")).strip().upper()


def _norm_chain(s: Any) -> str:
    # Упрощённая нормализация кода сети
    return _upper_clean(s).replace(" ", "").replace("-", "").replace("_", "")


def _json_safe(obj: Any) -> Any:
    # Приводим Decimal к строкам внутри dict/list, чтобы JSONField не падал
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


def _site_sets() -> tuple[set[str], set[str]]:
    ss: SiteSetup = SiteSetup.get_solo()
    # стейблы — регистронезависимо (casefold())
    stables = {p.strip().casefold() for p in (ss.stablecoins or "").replace(";", ",").split(",") if p.strip()}
    # сети с MEMO — метод настроек отдаёт уже нормализованные коды (обычно UPPER)
    memo_chains = set(ss.get_memo_required_chains_set())
    return stables, memo_chains


def _currency_map_for_exchange(exchange_id: int) -> dict[tuple[str, str], tuple[str, str]]:
    """
    (provider_symbol, provider_chain) -> (asset_code, chain_code)
    Ключ — в UPPER; если нет CurrencyMap, возвращаем пусто.
    """
    out: dict[tuple[str, str], tuple[str, str]] = {}
    if not CurrencyMap:
        return out
    try:
        for row in CurrencyMap.objects.filter(exchange_id=exchange_id).values(
            "external_symbol", "external_chain", "asset_code", "chain_code"
        ):
            ext_sym = _upper_clean(row["external_symbol"])
            ext_chain = _upper_clean(row["external_chain"])
            asset = _upper_clean(row["asset_code"])
            chain = _upper_clean(row["chain_code"])
            out[(ext_sym, ext_chain)] = (asset, chain or "NATIVE")
    except Exception:
        pass
    return out


def _map_codes(mapping: dict, provider_symbol: str, provider_chain: str) -> tuple[str, str]:
    key = (_upper_clean(provider_symbol), _upper_clean(provider_chain))
    return mapping.get(key, (key[0], (key[1] or "NATIVE")))


def _ensure_withdraw_conf_ge_deposit(conf_d: int, conf_w: int) -> tuple[int, int]:
    # для крипты на вход минимум 1 (твое правило), вывод не меньше входа
    conf_d = max(int(conf_d or 0), 1)
    conf_w = max(int(conf_w or 0), conf_d)
    return conf_d, conf_w


# ---------- HTTP к HTX ----------

def _htx_get(path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Dict[str, Any]:
    url = f"https://{_HTX_HOST}{path}"
    r = requests.get(url, params=params or {}, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return r.json() or {}


def _htx_sign_params(method: str, host: str, path: str, params: Dict[str, Any], secret_key: str) -> str:
    """
    Подпись Huobi/HTX: SignatureVersion=2, HmacSHA256, Base64
    StringToSign = "{METHOD}\n{host}\n{path}\n{CanonicalQueryString}"
    CanonicalQueryString — параметры отсортированы по ключу и urlencoded.
    """
    from urllib.parse import urlencode, quote

    qs = urlencode(sorted(params.items()), safe="~", quote_via=quote)
    payload = "\n".join([method.upper(), host, path, qs])
    digest = hmac.new(secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _htx_private_get(path: str, api_key: str, api_secret: str, extra_params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Dict[str, Any]:
    from urllib.parse import urlencode

    params: Dict[str, Any] = {
        "AccessKeyId": api_key,
        "SignatureMethod": "HmacSHA256",
        "SignatureVersion": "2",
        "Timestamp": _now_utc_iso(),
    }
    if extra_params:
        params.update(extra_params)
    params["Signature"] = _htx_sign_params("GET", _HTX_HOST, path, params, api_secret)

    url = f"https://{_HTX_HOST}{path}?{urlencode(params)}"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return r.json() or {}


# ---------- Адаптер ----------

class HtxAdapter(ProviderAdapter):
    """
    Адаптер HTX (Huobi) к нашему ExchangeAsset.
    Публичные источники:
      - /v2/reference/currencies  — валюты/цепи, статусы D/W, типы комиссий (fixed|ratio), maxWithdrawAmt
      - /v1/settings/common/currencys — fc/sc (подтверждения), dma/wma (минимумы), cawt (addr-tag), sp (precision)
    Приватные (если заданы ключи в ExchangeApiKey):
      - /v2/account/withdraw/quota — уточнение maxWithdrawAmt (приоритетнее публичного)
    """

    code = LiquidityProvider.HTX

    def sync(
        self,
        exchange: Exchange,
        *,
        timeout: int = 20,
        limit: Optional[int] = None,
        reconcile: bool = True,
        verbose: bool = False,
    ) -> dict:
        stats = {"created": 0, "updated": 0, "disabled": 0, "total_seen": 0}
        stable_set, memo_chain_set = _site_sets()
        cur_map = _currency_map_for_exchange(exchange.id)

        # 1) Публичные настройки валют (fc/sc, sp, cawt...)
        settings_map: dict[str, dict] = {}
        try:
            s = _htx_get("/v1/settings/common/currencys", timeout=timeout)
            if s.get("status") == "ok":
                for row in s.get("data") or []:
                    sym = _upper_clean(row.get("dn") or row.get("name"))
                    if sym:
                        settings_map[sym] = row
        except Exception:
            if verbose:
                print("[HTX] warn: /v1/settings/common/currencys unavailable, continue with /v2/reference/currencies only")

        # 2) Публичный справочник валют/цепей
        ref = _htx_get("/v2/reference/currencies", timeout=timeout)
        items: Iterable[dict] = ref.get("data") or []

        # 3) Опционально приватные квоты вывода
        ak = ExchangeApiKey.objects.filter(exchange=exchange, is_enabled=True).order_by("id").first()
        api_key = (ak.api_key or "") if ak else ""
        api_sec = (ak.api_secret or "") if ak else ""
        have_private = bool(api_key and api_sec)

        seen: set[tuple[str, str]] = set()

        with transaction.atomic():
            total = 0
            for it in items:
                sym = _upper_clean(it.get("currency"))
                chains: Iterable[dict] = it.get("chains") or []

                # нет цепей → трактуем как фиат (виртуальная цепь FIAT)
                if not chains:
                    asset_code, chain_code = _map_codes(cur_map, sym, "FIAT")
                    seen.add((asset_code, chain_code))
                    total += 1

                    is_stable = (sym.casefold() in stable_set)
                    srow = settings_map.get(sym, {})
                    amount_precision_display = _as_int(srow.get("sp"), 8)

                    defaults = dict(
                        asset_name=srow.get("fn") or sym,
                        chain_name="FIAT",
                        asset_kind="FIAT",
                        AD=True, AW=True,  # автофлаги включены; ручные D/W не трогаем
                        confirmations_deposit=1,
                        confirmations_withdraw=1,
                        requires_memo=False,
                        is_stablecoin=is_stable,
                        amount_precision=amount_precision_display or 8,
                        amount_precision_display=amount_precision_display or 8,
                        deposit_fee_percent=Decimal("0"),
                        deposit_fee_fixed=Decimal("0"),
                        withdraw_fee_percent=Decimal("0"),
                        withdraw_fee_fixed=Decimal("0"),
                        deposit_min=Decimal("0"),
                        deposit_max=Decimal("0"),
                        withdraw_min=Decimal("0"),
                        withdraw_max=Decimal("0"),
                        provider_symbol=sym,
                        provider_chain="FIAT",
                        raw_metadata=_json_safe(it),
                        last_synced_at=timezone.now(),
                    )

                    obj, created = ExchangeAsset.objects.get_or_create(
                        exchange=exchange, asset_code=asset_code, chain_code=chain_code, defaults=defaults
                    )
                    if created:
                        stats["created"] += 1
                    else:
                        changed = False
                        for f, v in defaults.items():
                            if getattr(obj, f) != v:
                                setattr(obj, f, v)
                                changed = True
                        if changed:
                            obj.save(update_fields=list(defaults.keys()))
                            stats["updated"] += 1
                    if limit and total >= limit:
                        break
                    continue

                # есть цепи — крипта
                for ch in chains:
                    base_chain = _norm_chain(ch.get("baseChain") or "")
                    proto = _norm_chain(ch.get("baseChainProtocol") or "")
                    declared_chain = _norm_chain(ch.get("chain") or "")
                    chain_code_src = proto or base_chain or declared_chain or "CHAIN"
                    chain_name = ch.get("displayName") or (proto or base_chain) or chain_code_src

                    asset_code, chain_code = _map_codes(cur_map, sym, chain_code_src)
                    seen.add((asset_code, chain_code))
                    total += 1

                    # автофлаги на уровне цепи
                    ad = _bool(ch.get("depositStatus"), default=True)
                    aw = _bool(ch.get("withdrawStatus"), default=True)

                    # подтверждения из settings (fc/sc), иначе 1/1
                    srow = settings_map.get(sym, {})
                    conf_d, conf_w = _ensure_withdraw_conf_ge_deposit(
                        _as_int(srow.get("fc") or ch.get("confirmations") or 1, 1),
                        _as_int(srow.get("sc") or 0, 0),
                    )

                    # лимиты из settings (dma/wma), если есть; плюс возможные max из reference
                    dmin = _as_dec(srow.get("dma"))
                    wmin = _as_dec(srow.get("wma"))
                    wmax = _as_dec(ch.get("maxWithdrawAmt"))

                    # комиссии вывода: fixed / ratio
                    withdraw_fee_fixed = Decimal("0")
                    withdraw_fee_percent = Decimal("0")
                    fee_type = str(ch.get("withdrawFeeType") or "").lower()
                    if fee_type == "fixed":
                        withdraw_fee_fixed = _as_dec(ch.get("transactFeeWithdraw"))
                    elif fee_type == "ratio":
                        rate = _as_dec(ch.get("transactFeeRateWithdraw"))
                        withdraw_fee_percent = rate * Decimal("100")
                    else:
                        if ch.get("transactFeeWithdraw") is not None:
                            withdraw_fee_fixed = _as_dec(ch.get("transactFeeWithdraw"))
                        if ch.get("transactFeeRateWithdraw") is not None:
                            withdraw_fee_percent = _as_dec(ch.get("transactFeeRateWithdraw")) * Decimal("100")

                    # депозиты у HTX обычно без комиссии
                    deposit_fee_fixed = Decimal("0")
                    deposit_fee_percent = Decimal("0")

                    # memo: по списку из SiteSetup либо по флагу cawt (addr-tag) из settings
                    requires_memo = (chain_code in memo_chain_set) or _bool(srow.get("cawt"), False)

                    # стейбл только по SiteSetup (HTX явного флага не даёт)
                    is_stable = (sym.casefold() in stable_set)

                    amount_precision_display = _as_int(srow.get("sp"), 8)
                    amount_precision = int(ch.get("displayPrecision") or amount_precision_display or 8)

                    defaults = dict(
                        asset_name=srow.get("fn") or sym,
                        chain_name=chain_name,
                        asset_kind="CRYPTO",
                        AD=ad, AW=aw,
                        confirmations_deposit=conf_d,
                        confirmations_withdraw=conf_w,
                        deposit_fee_percent=deposit_fee_percent,
                        deposit_fee_fixed=deposit_fee_fixed,
                        withdraw_fee_percent=withdraw_fee_percent,
                        withdraw_fee_fixed=withdraw_fee_fixed,
                        deposit_min=dmin,
                        deposit_max=_as_dec(srow.get("dmax") or 0),  # если когда-нибудь появится
                        withdraw_min=wmin,
                        withdraw_max=wmax,
                        requires_memo=requires_memo,
                        is_stablecoin=is_stable,
                        amount_precision=amount_precision,
                        amount_precision_display=amount_precision_display,
                        provider_symbol=sym,
                        provider_chain=chain_code_src,
                        raw_metadata=_json_safe({"ref": ch, "settings": srow}),
                        last_synced_at=timezone.now(),
                    )

                    obj, created = ExchangeAsset.objects.get_or_create(
                        exchange=exchange, asset_code=asset_code, chain_code=chain_code, defaults=defaults
                    )
                    if created:
                        stats["created"] += 1
                    else:
                        changed = False
                        for f, v in defaults.items():
                            if getattr(obj, f) != v:
                                setattr(obj, f, v)
                                changed = True
                        if changed:
                            obj.save(update_fields=list(defaults.keys()))
                            stats["updated"] += 1

                    # приватные квоты имеют приоритет — если есть ключи, подтянем maxWithdrawAmt
                    if have_private:
                        try:
                            q = _htx_private_get(
                                "/v2/account/withdraw/quota",
                                api_key, api_sec,
                                {"currency": sym.lower()},
                                timeout=timeout,
                            )
                            data = q.get("data") or {}
                            chains_q = data.get("chains") or []
                            if chains_q:
                                best = None
                                for row in chains_q:
                                    mw = _as_dec(row.get("maxWithdrawAmt"))
                                    if mw and (best is None or mw > best):
                                        best = mw
                                if best is not None and best != obj.withdraw_max:
                                    obj.withdraw_max = best
                                    obj.save(update_fields=["withdraw_max"])
                                    stats["updated"] += 1
                        except Exception:
                            if verbose:
                                print(f"[HTX] warn: private quota failed for {sym}")

                    if limit and total >= limit:
                        break

            stats["total_seen"] = total

            # reconcile: у того же exchange погасим автофлаги там, где (asset_code, chain_code) не пришли
            if reconcile:
                for obj in ExchangeAsset.objects.filter(exchange=exchange).only("id", "asset_code", "chain_code", "AD", "AW"):
                    if (obj.asset_code, obj.chain_code) not in seen and (obj.AD or obj.AW):
                        obj.AD = False
                        obj.AW = False
                        obj.last_synced_at = timezone.now()
                        obj.save(update_fields=["AD", "AW", "last_synced_at"])
                        stats["disabled"] += 1

        if verbose:
            print(f"[HTX] {stats}")
        return stats
