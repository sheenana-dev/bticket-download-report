from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.stores.google_play import GooglePlayClient

SAMPLE_CSV_UTF16 = (
    "Date,Daily Device Installs,Daily Device Uninstalls,Daily Device Upgrades,"
    "Total User Installs,Daily User Installs,Daily User Uninstalls,Active Device Installs\n"
    "2026-02-08,120,10,5,50000,118,8,45000\n"
    "2026-02-09,150,12,3,50150,148,10,45100\n"
    "2026-02-10,200,15,8,50350,195,12,45200\n"
)


@patch("src.stores.google_play.storage.Client")
def test_fetch_report_success(mock_storage_cls, google_play_config):
    mock_client = MagicMock()
    mock_storage_cls.return_value = mock_client

    mock_blob = MagicMock()
    mock_blob.download_as_text.return_value = SAMPLE_CSV_UTF16
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client.bucket.return_value = mock_bucket

    client = GooglePlayClient(google_play_config)
    client.client = mock_client

    result = client.fetch_report(date(2026, 2, 10))

    assert result.store_name == "Google Play"
    assert result.daily_downloads == 200
    assert result.total_downloads is None  # cumulative tracked in main.py, not from CSV
    assert result.data_date == "Feb 10"
    assert result.error_message is None


@patch("src.stores.google_play.storage.Client")
def test_fetch_report_data_not_available(mock_storage_cls, google_play_config):
    mock_client = MagicMock()
    mock_storage_cls.return_value = mock_client

    mock_blob = MagicMock()
    mock_blob.download_as_text.return_value = SAMPLE_CSV_UTF16
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client.bucket.return_value = mock_bucket

    client = GooglePlayClient(google_play_config)
    client.client = mock_client

    # Request a date not in the CSV (Feb 11) — should fall back to Feb 10
    result = client.fetch_report(date(2026, 2, 11))

    assert result.daily_downloads == 200  # Falls back to Feb 10
    assert result.data_date == "Feb 10"


@patch("src.stores.google_play.storage.Client")
def test_fetch_report_gcs_error(mock_storage_cls, google_play_config):
    mock_client = MagicMock()
    mock_storage_cls.return_value = mock_client
    mock_client.bucket.side_effect = Exception("Bucket not found")

    client = GooglePlayClient(google_play_config)
    client.client = mock_client

    result = client.fetch_report(date(2026, 2, 10))

    assert result.store_name == "Google Play"
    assert result.daily_downloads is None
    assert "delayed" in (result.data_date or "")


def test_safe_int():
    assert GooglePlayClient._safe_int("1,234") == 1234
    assert GooglePlayClient._safe_int("0") == 0
    assert GooglePlayClient._safe_int(None) is None
    assert GooglePlayClient._safe_int("N/A") is None
    assert GooglePlayClient._safe_int("  500  ") == 500
