"""Tests for churn (uninstalls): Google export summing. Rendering: test_combined_report."""

from datetime import date
from unittest.mock import MagicMock, patch

from src.stores.google_play import GooglePlayClient


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
