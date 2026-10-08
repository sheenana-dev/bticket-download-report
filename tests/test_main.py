"""collect_downloads(): fetch + cumulative bookkeeping + per-store results.

History writes and CSV reads are stubbed so tests never touch data/.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.stores.base import StoreResult

NOW = datetime(2026, 2, 11, 16, 37, tzinfo=ZoneInfo("Asia/Manila"))


def _config():
    cfg = MagicMock()
    cfg.timezone = "Asia/Manila"
    return cfg


def _google(result: StoreResult) -> MagicMock:
    client = MagicMock()
    client.fetch_report.return_value = result
    client.fetch_recent_reports.return_value = []
    client.fetch_churn.return_value = (None, None)
    return client


@patch("src.report.get_latest_per_platform", return_value={})  # no CSV -> fall back to API results
@patch("src.main.save_to_history")
@patch("src.main.GooglePlayClient")
@patch("src.main.AppleStoreClient")
@patch("src.main.save_cumulative_totals")
@patch("src.main.load_cumulative_totals", return_value={"apple": 1000, "google_play": 2000})
def test_collect_downloads_adds_new_day_to_totals(
    _load, mock_save_cum, mock_apple_cls, mock_google_cls, _save_hist, _latest,
):
    from src.main import collect_downloads

    mock_apple_cls.return_value.fetch_report.return_value = StoreResult(
        "App Store", daily_downloads=100, data_date="Feb 10")
    mock_google_cls.return_value = _google(StoreResult(
        "Google Play", daily_downloads=200, data_date="Feb 10"))

    results = collect_downloads(_config(), NOW)

    by_store = {r.store_name: r for r in results}
    assert by_store["App Store"].total_downloads == 1100
    assert by_store["Google Play"].total_downloads == 2200
    saved = mock_save_cum.call_args[0][0]
    assert saved["apple"] == 1100 and saved["apple_last_date"] == "Feb 10"


@patch("src.report.get_latest_per_platform", return_value={})
@patch("src.main.save_to_history")
@patch("src.main.GooglePlayClient")
@patch("src.main.AppleStoreClient")
@patch("src.main.save_cumulative_totals")
@patch("src.main.load_cumulative_totals",
       return_value={"apple": 1000, "apple_last_date": "Feb 10", "google_play": 2000})
def test_collect_downloads_same_day_is_not_double_counted(
    _load, mock_save_cum, mock_apple_cls, mock_google_cls, _save_hist, _latest,
):
    from src.main import collect_downloads

    mock_apple_cls.return_value.fetch_report.return_value = StoreResult(
        "App Store", daily_downloads=100, data_date="Feb 10")
    mock_google_cls.return_value = _google(StoreResult("Google Play", daily_downloads=0, data_date="Feb 10"))

    collect_downloads(_config(), NOW)

    assert mock_save_cum.call_args[0][0]["apple"] == 1000


@patch("src.report.get_latest_per_platform", return_value={})
@patch("src.main.save_to_history")
@patch("src.main.GooglePlayClient")
@patch("src.main.AppleStoreClient")
@patch("src.main.save_cumulative_totals")
@patch("src.main.load_cumulative_totals", return_value={"apple": 1000, "google_play": 2000})
def test_collect_downloads_store_failure_is_isolated(
    _load, _save_cum, mock_apple_cls, mock_google_cls, _save_hist, _latest,
):
    from src.main import collect_downloads

    mock_apple_cls.return_value.fetch_report.return_value = StoreResult(
        "App Store", error_message="Auth failed")
    mock_google_cls.return_value = _google(StoreResult(
        "Google Play", daily_downloads=200, data_date="Feb 10"))

    by_store = {r.store_name: r for r in collect_downloads(_config(), NOW)}

    assert by_store["App Store"].error_message == "Auth failed"
    assert by_store["Google Play"].total_downloads == 2200


@patch("src.daily.main", return_value=0)
def test_src_main_is_alias_for_combined_report(mock_daily, monkeypatch):
    from src.main import main

    monkeypatch.setattr("sys.argv", ["src.main", "--dry-run"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    mock_daily.assert_called_once_with(["--dry-run"])
