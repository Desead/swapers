import pytest
from decimal import Decimal

from app_market.providers import numeric as N
from app_market.models.exchange_asset import AssetKind

pytestmark = pytest.mark.django_db


# ---------- D ----------
def test_D_basic_and_caps():
    assert N.D("1.234") == Decimal("1.234")
    assert N.D(Decimal("2")) == Decimal("2")
    assert N.D(None) == Decimal("0")
    assert N.D("") == Decimal("0")
    assert N.D("NaN") == Decimal("0")

    # «большое число» должно клампиться к допустимому финитному значению симметрично
    big_pos = N.D("1e30")
    big_neg = N.D("-1e30")
    assert big_pos > 0 and big_neg < 0
    assert big_pos == -big_neg  # симметрия по модулю


# ---------- U / disp / B ----------
def test_U_and_disp_and_B():
    assert N.U(" eth  ") == "ETH"
    assert N.disp("  x y  ") == "x y"

    # B: явные true/false
    assert N.B(True) is True
    assert N.B(False) is False
    # строки
    assert N.B("true") is True
    assert N.B("False") is False
    assert N.B("enabled") is True
    assert N.B("disabled") is False
    # числа
    assert N.B(1) is True
    assert N.B(0) is False
    # первое явное значение из нескольких
    assert N.B(None, "", "yes") is True
    assert N.B(None, "", "no") is False


# ---------- ensure_wd_conf_ge_dep ----------
def test_ensure_wd_conf_ge_dep():
    dep, wd = N.ensure_wd_conf_ge_dep(7, 5)
    assert (dep, wd) == (7, 7)
    dep, wd = N.ensure_wd_conf_ge_dep(10, 12)
    assert (dep, wd) == (10, 12)


# ---------- json_safe ----------
def test_json_safe_recursively_serializes_decimal():
    obj = {
        "a": Decimal("1.23"),
        "b": [Decimal("0.1"), {"c": Decimal("2.5")}],
        "d": "ok",
    }
    js = N.json_safe(obj)
    # все Decimal должны стать строками
    assert js["a"] == "1.23"
    assert js["b"][0] == "0.1"
    assert js["b"][1]["c"] == "2.5"
    assert js["d"] == "ok"


# ---------- infer_asset_kind ----------
def test_infer_asset_kind_for_netchain_assets_only():
    """
    Текущая логика: CRYPTO решается по наличию chain в конвейере.
    Для «без сетей» numeric классифицирует только FIAT / NOTDEFINED.
    """
    fiat = {"USD", "EUR"}

    # фиат по тикеру
    assert N.infer_asset_kind("usd", "", "", fiat_codes=fiat) == AssetKind.FIAT
    # фиат по подсказкам (сеть/имя)
    assert N.infer_asset_kind("BANKX", "bank", "", fiat_codes=fiat) == AssetKind.FIAT
    # всё остальное без сетей → NOTDEFINED (а не CRYPTO)
    assert N.infer_asset_kind("BTC", "", "Ethereum", fiat_codes=fiat) == AssetKind.NOTDEFINED


# ---------- stable_set / memo_required_set / fiat_set ----------
def test_sets_from_siteset_monkeypatched(monkeypatch):
    """
    Здесь не полагаемся на реальную БД SiteSetup — подменяем класс в numeric.
    """
    class StubSS:
        # даём «чистые» токены, чтобы не плодить «USD»+«C»
        stablecoins = "USDT,USDC,DAI"
        memo_required_chains = " tron ; xlm "
        fiat_name = " usd , EUR "

        @classmethod
        def get_solo(cls):
            return cls()

    # подменяем используемый внутри numeric класс
    monkeypatch.setattr(N, "SiteSetup", StubSS)

    assert N.stable_set() == {"USDT", "USDC", "DAI"}
    assert N.memo_required_set() == {"TRON", "XLM"}
    assert N.fiat_set() == {"USD", "EUR"}
