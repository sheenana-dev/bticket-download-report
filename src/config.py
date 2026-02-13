import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppleConfig:
    issuer_id: str
    key_id: str
    private_key: str
    vendor_number: str
    app_sku: str


@dataclass(frozen=True)
class GooglePlayConfig:
    package_name: str
    bucket_id: str


@dataclass(frozen=True)
class HuaweiConfig:
    client_id: str
    client_secret: str
    app_id: str


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class AppConfig:
    apple: AppleConfig
    google_play: GooglePlayConfig
    telegram: TelegramConfig
    timezone: str = "Asia/Manila"


def load_config() -> AppConfig:
    """Load and validate all configuration from environment variables."""
    missing = []

    def _get(name: str) -> str:
        val = os.environ.get(name, "").strip()
        if not val:
            missing.append(name)
            return ""
        return val

    apple = AppleConfig(
        issuer_id=_get("APPLE_ISSUER_ID"),
        key_id=_get("APPLE_KEY_ID"),
        private_key=_get("APPLE_PRIVATE_KEY").replace("\\n", "\n"),
        vendor_number=_get("APPLE_VENDOR_NUMBER"),
        app_sku=_get("APPLE_APP_SKU"),
    )

    google_play = GooglePlayConfig(
        package_name=_get("GOOGLE_PACKAGE_NAME"),
        bucket_id=_get("GOOGLE_BUCKET_ID"),
    )

    telegram = TelegramConfig(
        bot_token=_get("TELEGRAM_BOT_TOKEN"),
        chat_id=_get("TELEGRAM_CHAT_ID"),
    )

    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    return AppConfig(
        apple=apple,
        google_play=google_play,
        telegram=telegram,
    )
