import pytest

from src.config import AppleConfig, GooglePlayConfig, HuaweiConfig, TelegramConfig


@pytest.fixture
def apple_config():
    return AppleConfig(
        issuer_id="test-issuer-id",
        key_id="test-key-id",
        private_key=(
            "-----BEGIN EC PRIVATE KEY-----\n"
            "MHQCAQEEIBkg4LVWM9nuwNSk3yByxZpYRTBnVFNMOHqlFxMGbkANoAcGBSuBBAAi\n"
            "oWQDYgAE2n4KhSMGmEP1SEOOKaxSPJYAR1CEYikpITfy+JLcb5MjbECOKBHE/MuH\n"
            "AbVMndpfbmQOB9jiGDALRMDMXNP3oMyIFDiERA+RclIjWmEqBiIe+Bab2GNP84Zy7\n"
            "VAq9eTMK\n"
            "-----END EC PRIVATE KEY-----\n"
        ),
        vendor_number="12345678",
        app_sku="com.bticket.app",
    )


@pytest.fixture
def google_play_config():
    return GooglePlayConfig(
        package_name="com.bticket.app",
        bucket_id="01234567890987654321",
    )


@pytest.fixture
def huawei_config():
    return HuaweiConfig(
        client_id="test-client-id",
        client_secret="test-client-secret",
        app_id="107654321",
    )


@pytest.fixture
def telegram_config():
    return TelegramConfig(
        bot_token="123456:ABC-DEF1234",
        chat_id="-1001234567890",
    )
