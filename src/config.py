import os
from dataclasses import dataclass, field
from typing import Optional


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
class RevenueConfig:
    """Settings for the subscription revenue report (all optional, env-driven).

    Every value has a safe default so the download job keeps running even if
    none of the REVENUE_* variables are set.
    """

    # Currency all figures are normalised to.
    report_currency: str = "PHP"
    # Estimated Google Play service fee used for the DAILY estimate only. The
    # monthly report uses the real fee lines from the earnings report.
    # 0.15 = 15% (Play's rate for subscriptions and for the first $1M/yr).
    google_fee_rate: float = 0.15
    # Huawei's IAP service fee for the daily estimate (0.15 for apps in the
    # Huawei small-developer programme, otherwise 0.30).
    huawei_fee_rate: float = 0.15
    # Huawei Reports API path for the IAP/payment export. Kept configurable
    # because Huawei's docs are region-inconsistent; `--probe huawei` prints the
    # raw response so the right path/columns can be pinned quickly.
    huawei_iap_report_path: str = (
        "/api/report/distribution-operation-quality/v1/IAPReportExport/{app_id}"
    )
    # CSV column carrying the paid amount in Huawei's export.
    huawei_amount_column: str = "Paid amount"
    huawei_count_column: str = "Paid orders"
    huawei_currency: str = "CNY"
    # Optional fixed FX overrides, e.g. "USD:56.2,JPY:0.38". Anything not listed
    # is fetched live from the FX provider and cached for the day.
    fx_overrides: dict = field(default_factory=dict)
    # Where daily revenue Telegram summaries go. Defaults to the download
    # report's chat if unset.
    chat_id: Optional[str] = None


@dataclass(frozen=True)
class AppConfig:
    apple: AppleConfig
    google_play: GooglePlayConfig
    telegram: TelegramConfig
    huawei: Optional[HuaweiConfig] = None
    revenue: RevenueConfig = field(default_factory=RevenueConfig)
    timezone: str = "Asia/Manila"


def _parse_fx_overrides(raw: str) -> dict:
    out: dict = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        code, rate = pair.split(":", 1)
        try:
            out[code.strip().upper()] = float(rate)
        except ValueError:
            continue
    return out


def _load_optional_huawei() -> Optional[HuaweiConfig]:
    client_id = os.environ.get("HUAWEI_CLIENT_ID", "").strip()
    client_secret = os.environ.get("HUAWEI_CLIENT_SECRET", "").strip()
    app_id = os.environ.get("HUAWEI_APP_ID", "").strip()
    if client_id and client_secret and app_id:
        return HuaweiConfig(client_id=client_id, client_secret=client_secret, app_id=app_id)
    return None


def _load_revenue() -> RevenueConfig:
    env = os.environ
    defaults = RevenueConfig()

    def _float(name: str, default: float) -> float:
        try:
            return float(env.get(name, "").strip() or default)
        except ValueError:
            return default

    return RevenueConfig(
        report_currency=env.get("REVENUE_CURRENCY", "").strip().upper() or defaults.report_currency,
        google_fee_rate=_float("REVENUE_GOOGLE_FEE_RATE", defaults.google_fee_rate),
        huawei_fee_rate=_float("REVENUE_HUAWEI_FEE_RATE", defaults.huawei_fee_rate),
        huawei_iap_report_path=env.get("HUAWEI_IAP_REPORT_PATH", "").strip() or defaults.huawei_iap_report_path,
        huawei_amount_column=env.get("HUAWEI_IAP_AMOUNT_COLUMN", "").strip() or defaults.huawei_amount_column,
        huawei_count_column=env.get("HUAWEI_IAP_COUNT_COLUMN", "").strip() or defaults.huawei_count_column,
        huawei_currency=env.get("HUAWEI_IAP_CURRENCY", "").strip().upper() or defaults.huawei_currency,
        fx_overrides=_parse_fx_overrides(env.get("REVENUE_FX_OVERRIDES", "")),
        chat_id=env.get("REVENUE_TELEGRAM_CHAT_ID", "").strip() or None,
    )


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
        huawei=_load_optional_huawei(),
        revenue=_load_revenue(),
    )
