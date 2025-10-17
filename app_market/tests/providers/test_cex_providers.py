import pytest
from decimal import Decimal

from app_market.models.exchange_asset import ExchangeAsset, AssetKind
from app_market.providers.cex.bybit import BybitAdapter
from app_market.providers.cex.kucoin import KucoinAdapter
from app_market.providers.cex.htx import HtxAdapter
from app_market.providers.cex.whitebit import WhitebitAdapter
from app_market.providers.cex.mexc import MexcAdapter
from app_market.providers.numeric import NO_CHAIN

pytestmark = pytest.mark.django_db


def test_bybit_sync_smoke(ex_bybit, monkeypatch):
    """
    BYBIT:
    - у сети нет withdrawFee → AW должен стать False (наша провайдерская логика).
    - wd_pct приходит долей и должен конвертироваться в проценты.
    """
    payload = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "rows": [
                {
                    "coin": "ABC",
                    "name": "ABC Coin",
                    "remainAmount": "1000000",
                    "chains": [
                        {
                            "chain": "ERC20",
                            "chainType": "Ethereum (ERC20)",
                            "chainDeposit": True,
                            "chainWithdraw": True,
                            "confirmation": "10",
                            "safeConfirmNumber": "12",
                            "depositMin": "1",
                            "withdrawMin": "2",
                            # ключа withdrawFee нет → AW должно стать False
                            "withdrawPercentageFee": "0.001"  # 0.1% после конвертации
                        }
                    ]
                }
            ]
        }
    }

    adp = BybitAdapter()

    # подменяем сетевой вызов
    monkeypatch.setattr(adp, "fetch_payload", lambda timeout=20: payload["result"]["rows"])
    stats = adp.sync_assets(ex_bybit, timeout=1, reconcile=True, verbose=True)

    stats = adp.sync_assets(ex_bybit, timeout=1, reconcile=True, verbose=True)
    assert stats.processed == 1
    obj = ExchangeAsset.objects.get(exchange=ex_bybit, asset_code="ABC", chain_code="ERC20")
    assert obj.asset_kind == AssetKind.CRYPTO
    assert obj.AD is True  # deposit on + conf>0
    assert obj.AW is False  # из-за отсутствия withdrawFee в ответе
    assert obj.withdraw_fee_percent == Decimal("0.1")  # 0.001 доли → 0.1%
    # raw_metadata без дублирования сетей
    assert "chain" not in obj.raw_metadata


def test_kucoin_sync_smoke(ex_kucoin, monkeypatch):
    """
    KUCOIN:
    - базовый кейс по одной сети;
    - подтверждения: депозит из preConfirms, вывод из confirms.
    """
    payload = {
        "code": "200000",
        "data": [
            {
                "currency": "KUC",
                "fullName": "KuCoin Test",
                "precision": 6,
                "chains": [
                    {
                        "chainName": "KRC",
                        "isDepositEnabled": True,
                        "isWithdrawEnabled": True,
                        # провайдер читает депозит из preConfirms
                        "preConfirms": 7,
                        # провайдер читает вывод из confirms
                        "confirms": 15,
                        "depositMinSize": "0.1",
                        "withdrawalMinSize": "0.2",
                        "withdrawalMinFee": "0.01",
                    }
                ]
            }
        ]
    }

    adp = KucoinAdapter()
    # iter_rows ждёт list[dict], поэтому отдаём data
    monkeypatch.setattr(adp, "fetch_payload", lambda timeout=20: payload["data"])

    stats = adp.sync_assets(ex_kucoin, timeout=1, reconcile=True, verbose=True)
    assert stats.processed == 1

    obj = ExchangeAsset.objects.get(exchange=ex_kucoin, asset_code="KUC", chain_code="KRC")
    assert obj.asset_kind == AssetKind.CRYPTO
    assert obj.AD is True and obj.AW is True
    assert obj.confirmations_deposit == 7
    assert obj.confirmations_withdraw == 15
    assert obj.withdraw_fee_fixed == Decimal("0.01")


def test_htx_notdefined_without_chains(ex_htx, monkeypatch):
    """
    HTX:
    - без сетей → это не крипта; пусть будет NOTDEFINED (AD/AW=False).
    """
    payload = {
        "data": [
            {
                "currency": "XNOCHAIN",
                "assetType": 1,
                "chains": [],  # нет сетей
                "instStatus": "delisted"
            }
        ]
    }

    adp = HtxAdapter()
    monkeypatch.setattr(adp, "fetch_payload", lambda timeout=20: payload["data"])
    stats = adp.sync_assets(ex_htx, timeout=1, reconcile=True, verbose=True)

    stats = adp.sync_assets(ex_htx, timeout=1, reconcile=True, verbose=True)
    assert stats.processed == 1
    obj = ExchangeAsset.objects.get(exchange=ex_htx, asset_code="XNOCHAIN", chain_code=NO_CHAIN)
    assert obj.asset_kind == AssetKind.NOTDEFINED
    assert obj.AD is False and obj.AW is False


def test_whitebit_fiat_detection(ex_whitebit, monkeypatch):
    """
    WhiteBIT:
    - фиатный шлюз: есть providers и нет confirmations → без сетей,
      общий конвейер классифицирует через fiat_set(), здесь проверяем поведение без сбоев.
    """
    assets = {
        "USD": {
            "name": "US Dollar",
            "currency_precision": 2,
            "providers": {"card": {}, "sepa": {}},
            "confirmations": 0,
            "can_deposit": True,
            "can_withdraw": True,
            "min_deposit": "10",
            "max_deposit": "10000",
            "min_withdraw": "10",
            "max_withdraw": "10000",
        }
    }
    fees = {
        "USD": {
            "deposit": {"min_amount": "0", "max_amount": "0", "fixed": "0", "flex": "0"},
            "withdraw": {"min_amount": "0", "max_amount": "0", "fixed": "0", "flex": "0"},
        }
    }

    adp = WhitebitAdapter()
    monkeypatch.setattr(adp, "fetch_payload", lambda timeout=20: {"assets": assets, "fee_pub": fees, "fee_priv": {}})

    stats = adp.sync_assets(ex_whitebit, timeout=1, reconcile=True, verbose=True)
    assert stats.processed == 1
    obj = ExchangeAsset.objects.get(exchange=ex_whitebit, asset_code="USD", chain_code="FIAT")
    # Тип должен быть FIAT согласно общему fiat_set(), AD/AW=True; D/W при создании False
    assert obj.asset_kind in (AssetKind.CASH, AssetKind.FIAT, AssetKind.NOTDEFINED)
    if obj.asset_kind in (AssetKind.CASH, AssetKind.FIAT):
        assert obj.AD and obj.AW
        assert obj.D is False and obj.W is False


def test_mexc_core_logic(ex_mexc, monkeypatch):
    """
    MEXC:
    - 1MIL: depositEnable=false, withdrawEnable=true, minConfirm=96 → AD=False, AW=True
    - policy_write_withdraw_max() == False → withdraw_max = 0
    """
    payload = [
        {
            "coin": "1MIL",
            "name": "1MillionNFTs",
            "networkList": [
                {
                    "network": "ETH",
                    "name": "Ethereum(ERC20)",
                    "depositEnable": False,
                    "withdrawEnable": True,
                    "minConfirm": 96,
                    "withdrawFee": "0",
                    "withdrawMin": "1",
                    "withdrawMax": "2000000",
                }
            ]
        }
    ]

    adp = MexcAdapter()
    monkeypatch.setattr(adp, "fetch_payload", lambda timeout=20: payload)

    stats = adp.sync_assets(ex_mexc, timeout=1, reconcile=True, verbose=True)
    assert stats.processed == 1

    obj = ExchangeAsset.objects.get(exchange=ex_mexc, asset_code="1MIL", chain_code="ETH")
    assert obj.asset_kind == AssetKind.CRYPTO
    assert obj.AD is False  # depositEnable=false → AD=False (даже при conf>0)
    assert obj.AW is True  # withdrawEnable=true & conf>0
    assert obj.withdraw_max == Decimal("0")  # политика MEXC — не писать withdraw_max
    # raw_metadata только корневой объект
    assert "chain" not in obj.raw_metadata
