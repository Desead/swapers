from __future__ import annotations

from typing import Any, Iterable, Dict, Tuple

from django.conf import settings

from app_market.providers.base import UnifiedProviderBase, ProviderRow
from app_market.providers.http import SESSION
from app_market.providers.numeric import D, U, B, stable_set

API_BASE = "https://api.rapira.net"
OPEN_TOKEN_URL = f"{API_BASE}/open/token"


def _include_rub() -> bool:
    try:
        return bool(getattr(settings, "RAPIRA_INCLUDE_RUB", True))
    except Exception:
        return True


def _rub_precision() -> int:
    try:
        return int(getattr(settings, "RAPIRA_RUB_PRECISION", 2))
    except Exception:
        return 2


def _conf_overrides() -> Dict[Tuple[str, str], int]:
    """
    Таблица подтверждений из настроек.
    Ключи берём как есть из Rapira: (coinId, chainId) → int(confirmations).
    Нормализуем к верхнему регистру так же, как данные из API.
    """
    raw = getattr(settings, "RAPIRA_CONFIRMATIONS", {})
    out: Dict[Tuple[str, str], int] = {}
    try:
        for (asset, chain), v in raw.items():
            a = U(str(asset))
            c = U(str(chain))
            out[(a, c)] = int(v)
    except Exception:
        pass
    return out


class RapiraAdapter(UnifiedProviderBase):
    """
    Rapira (https://rapira.net/)
    Источник списка валют по сетям: GET /open/token.
    Дополнительно добавляем синтетический FIAT-актив RUB (депозит/вывод недоступны).
    Подтверждения берём из таблицы оверрайдов RAPIRA_CONFIRMATIONS.
    ВАЖНО: если пары (asset, chain) нет в RAPIRA_CONFIRMATIONS — мы её пропускаем (не пишем в БД).
    """

    code = "RAPIRA"

    def provider_name_for_status(self) -> str:
        return "RAPIRA"

    def policy_write_withdraw_max(self) -> bool:
        # /open/token не возвращает лимиты max — не пишем withdraw_max
        return False

    # -------- fetch --------
    def fetch_payload(self, *, timeout: int) -> Any:
        resp = SESSION.get(OPEN_TOKEN_URL, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []

    # -------- map -> ProviderRow --------
    def iter_rows(self, payload: Any) -> Iterable[ProviderRow]:
        """
        Пример элемента:
        {
          "coinId":"USDT","chainId":"TRX","displayName":"TRC20",
          "rechargeable":true,"withdrawable":true,
          "minRecharge":0.01,"minWithdraw":0.01,
          "scale":2,"rechargeFee":0.1,"withdrawFee":0
        }
        """
        stables = stable_set()
        conf_map = _conf_overrides()

        # 1) Крипта по сетям из /open/token — ТОЛЬКО то, что есть в RAPIRA_CONFIRMATIONS
        for item in payload or []:
            coin = U(str(item.get("coinId", "")))
            chain = U(str(item.get("chainId", "")))
            if not coin or not chain:
                continue

            # строгая фильтрация по таблице подтверждений
            conf = conf_map.get((coin, chain))
            if conf is None:
                # нет в таблице — пропускаем
                continue
            conf_dep = conf_wd = int(conf)

            disp_name = (item.get("displayName") or chain) or ""

            rechargeable = B(item.get("rechargeable"))
            withdrawable = B(item.get("withdrawable"))

            dep_min = D(item.get("minRecharge") or 0)
            wd_min = D(item.get("minWithdraw") or 0)
            dep_fee_fix = D(item.get("rechargeFee") or 0)
            wd_fee_fix = D(item.get("withdrawFee") or 0)

            scale = int(item.get("scale") or 8)

            yield ProviderRow(
                asset_code=coin,
                asset_name=coin,               # displayName описывает сеть, не актив
                chain_code=chain,
                chain_name=disp_name,

                AD=rechargeable,
                AW=withdrawable,

                conf_dep=conf_dep,
                conf_wd=conf_wd,

                dep_min=dep_min,
                dep_max=D(0),
                wd_min=wd_min,
                wd_max=D(0),

                dep_fee_pct=D(0),
                dep_fee_fix=dep_fee_fix,
                wd_fee_pct=D(0),
                wd_fee_fix=wd_fee_fix,

                requires_memo=False,
                amount_precision=scale,
                is_stable=(coin in stables),

                raw_meta=item,
            )

        # 2) Синтетический FIAT RUB (депозит/вывод отсутствуют в open-API)
        #    Не зависит от RAPIRA_CONFIRMATIONS.
        if _include_rub():
            rub_prec = _rub_precision()
            yield ProviderRow(
                asset_code="RUB",
                asset_name="Russian Ruble",
                chain_code="",
                chain_name="",

                AD=False,
                AW=False,

                conf_dep=0,
                conf_wd=0,

                dep_min=D(0),
                dep_max=D(0),
                wd_min=D(0),
                wd_max=D(0),

                dep_fee_pct=D(0),
                dep_fee_fix=D(0),
                wd_fee_pct=D(0),
                wd_fee_fix=D(0),

                requires_memo=False,
                amount_precision=rub_prec,
                is_stable=False,

                raw_meta={"synthetic": True, "note": "FIAT RUB added from Rapira adapter"},
            )
