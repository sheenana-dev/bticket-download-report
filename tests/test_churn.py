"""Tests for churn (uninstalls): Google export summing + report rendering."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from src.formatter import format_report
from src.stores.base import StoreResult
from src.stores.google_play import GooglePlayClient


def _time():
    return datetime(2026, 6, 30, 9, 0, 0, tzinfo=ZoneInfo("Asia/Manila"))


# ----- formatter renders churn only when present -----

def test_churn_line_rendered_both_languages():
    results = [
        StoreResult("Google Play", daily_downloads=83, total_downloads=1884,
                    data_date="Jun 30", daily_uninstalls=67, total_uninstalls=934),
    ]
    msg = format_report(results, _time())
    assert "Churn: 67 today | 934 total" in msg
    assert "アンインストール: 67 今日 | 934 累計" in msg


def test_churn_omitted_when_absent():
    results = [
        StoreResult("App Store", daily_downloads=14, total_downloads=599, data_date="Jul 05"),
    ]
    msg = format_report(results, _time())
    assert "Churn" not in msg
    assert "アンインストール" not in msg


# ----- GooglePlayClient.fetch_churn sums across months, exact package only -----

@patch("src.stores.google_play.storage.Client")
def test_fetch_churn_sums_uninstalls(_mock_storage_cls, google_play_config):
    client = GooglePlayClient(google_play_config)
    pkg = google_play_config.package_name

    def blob(name):
        b = MagicMock()
        b.name = name
        return b

    # two months for our package + one for a different package (must be ignored)
    client.client.list_blobs = MagicMock(return_value=[
        blob(f"stats/installs/installs_{pkg}_202605_overview.csv"),
        blob(f"stats/installs/installs_{pkg}_202606_overview.csv"),
        blob(f"stats/installs/installs_{pkg}.sit_202606_overview.csv"),
    ])

    may = "Date,Daily User Uninstalls\n2026-05-30,5\n2026-05-31,7\n"
    jun = "Date,Daily User Uninstalls\n2026-06-01,10\n2026-06-02,3\n"
    client._download_csv = MagicMock(side_effect=lambda ym: {"202605": may, "202606": jun}.get(ym))

    daily, total = client.fetch_churn(date(2026, 6, 2))

    assert total == 25          # 5 + 7 + 10 + 3
    assert daily == 3           # latest dated row (2026-06-02)
    # the .sit package's month must not have been downloaded
    assert client._download_csv.call_count == 2


@patch("src.stores.google_play.storage.Client")
def test_fetch_churn_none_when_no_data(_mock_storage_cls, google_play_config):
    client = GooglePlayClient(google_play_config)
    client.client.list_blobs = MagicMock(return_value=[])
    assert client.fetch_churn(date(2026, 6, 2)) == (None, None)
