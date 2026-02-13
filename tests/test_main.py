import json
import os
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.stores.base import StoreResult


@patch.dict(os.environ, {
    "APPLE_ISSUER_ID": "test",
    "APPLE_KEY_ID": "test",
    "APPLE_PRIVATE_KEY": "test",
    "APPLE_VENDOR_NUMBER": "test",
    "APPLE_APP_SKU": "test",
    "GOOGLE_PACKAGE_NAME": "test",
    "GOOGLE_BUCKET_ID": "test",
    "TELEGRAM_BOT_TOKEN": "test",
    "TELEGRAM_CHAT_ID": "test",
})
@patch("src.main.send_telegram_message", return_value=True)
@patch("src.main.GooglePlayClient")
@patch("src.main.AppleStoreClient")
@patch("src.main.save_cumulative_totals")
@patch("src.main.load_cumulative_totals", return_value={"apple": 1000, "google_play": 2000})
def test_main_success(
    mock_load_cum, mock_save_cum,
    mock_apple_cls, mock_google_cls,
    mock_telegram,
):
    mock_apple_cls.return_value.fetch_report.return_value = StoreResult(
        store_name="App Store", daily_downloads=100, data_date="Feb 10",
    )
    mock_google_cls.return_value.fetch_report.return_value = StoreResult(
        store_name="Google Play", daily_downloads=200, data_date="Feb 10",
    )

    from src.main import main
    main()

    # Verify telegram was called
    mock_telegram.assert_called_once()
    message = mock_telegram.call_args[0][1]
    assert "B-Ticket" in message

    # Verify cumulative totals were saved
    mock_save_cum.assert_called_once()
    saved = mock_save_cum.call_args[0][0]
    assert saved["apple"] == 1100  # 1000 + 100


@patch.dict(os.environ, {
    "APPLE_ISSUER_ID": "test",
    "APPLE_KEY_ID": "test",
    "APPLE_PRIVATE_KEY": "test",
    "APPLE_VENDOR_NUMBER": "test",
    "APPLE_APP_SKU": "test",
    "GOOGLE_PACKAGE_NAME": "test",
    "GOOGLE_BUCKET_ID": "test",
    "TELEGRAM_BOT_TOKEN": "test",
    "TELEGRAM_CHAT_ID": "test",
})
@patch("src.main.send_telegram_message", return_value=True)
@patch("src.main.GooglePlayClient")
@patch("src.main.AppleStoreClient")
@patch("src.main.save_cumulative_totals")
@patch("src.main.load_cumulative_totals", return_value={"apple": 1000, "google_play": 2000})
def test_main_partial_failure(
    mock_load_cum, mock_save_cum,
    mock_apple_cls, mock_google_cls,
    mock_telegram,
):
    mock_apple_cls.return_value.fetch_report.return_value = StoreResult(
        store_name="App Store", error_message="Auth failed",
    )
    mock_google_cls.return_value.fetch_report.return_value = StoreResult(
        store_name="Google Play", daily_downloads=200, data_date="Feb 10",
    )

    from src.main import main
    main()

    # Report should still be sent even with Apple failure
    mock_telegram.assert_called_once()
    message = mock_telegram.call_args[0][1]
    assert "Unavailable" in message
    assert "Google Play" in message
