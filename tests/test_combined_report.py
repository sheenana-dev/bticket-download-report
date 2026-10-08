"""Combined daily message: layout, failure isolation, and the entry point's send logic."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from src.combined_report import format_combined
from src.revenue.models import DailyRevenue, RevenueResult
from src.stores.base import StoreResult

NOW = datetime(2026, 10, 6, 23, 24, tzinfo=ZoneInfo("Asia/Manila"))
DAY = date(2026, 10, 5)


def _downloads():
    return [
        StoreResult("App Store", daily_downloads=0, total_downloads=905, data_date="Oct 05", stale_days=1),
        StoreResult("Google Play", daily_downloads=2, total_downloads=8204, data_date="Sep 25",
                    stale_days=11, daily_uninstalls=23, total_uninstalls=6935),
    ]


def _revenue():
    results = [
        RevenueResult("App Store", DAY, DAY, gross=99.0, net=86.0, transactions=1),
        RevenueResult("Google Play", DAY, DAY, gross=0.0, net=0.0),
        RevenueResult("Huawei", DAY, DAY, gross=0.0, net=0.0),
    ]
    mtd = {
        "appstore": {"gross": 198.0, "net": 171.0, "trials": 4},
        "googleplay": {"gross": 99.0, "net": 84.0, "trials": 0},
        "huawei": {"gross": 0.0, "net": 0.0, "trials": 0},
    }
    return DailyRevenue(results, mtd, DAY, "PHP")


def test_combined_renders_both_sections_compactly():
    msg = format_combined(_downloads(), _revenue(), NOW)

    assert msg.startswith("<pre>") and msg.endswith("</pre>")
    assert "📅 Oct 06 · 11:24 PM PHT" in msg
    assert "0 / 905" in msg and "·Oct 05" in msg
    assert "2 / 8,204" in msg and "⚠️11d" in msg
    assert "churn 解約 23 / 6,935" in msg
    assert "2 / 9,109" in msg                      # download totals
    assert "₱86 / ₱171" in msg and "1 paid" in msg and "4 trial MTD" in msg
    assert "₱0 / ₱84*" in msg                      # estimated store gets a star
    assert "₱86 / ₱255" in msg                     # revenue totals
    assert "* est." in msg
    assert msg.count("\n") < 20                    # the whole point: short


def test_fresh_store_has_no_stale_flag():
    msg = format_combined(_downloads(), _revenue(), NOW)
    ios_line = next(line for line in msg.splitlines() if "iOS" in line and "905" in line)
    assert "⚠️" not in ios_line


def test_churn_line_only_for_stores_with_uninstalls():
    msg = format_combined(_downloads(), _revenue(), NOW)
    assert msg.count("churn 解約") == 1  # Android only; iOS has no uninstall data


def test_failed_download_section_shows_unavailable():
    msg = format_combined(None, _revenue(), NOW)
    assert "📥 Downloads" in msg and "unavailable" in msg
    assert "₱86 / ₱255" in msg


def test_failed_revenue_section_shows_unavailable():
    msg = format_combined(_downloads(), None, NOW)
    assert "💰 Net revenue" in msg and "unavailable" in msg
    assert "2 / 9,109" in msg
    assert "* est." not in msg


def test_single_store_errors_are_isolated():
    rev = _revenue()
    rev.results[2] = RevenueResult("Huawei", DAY, DAY, error_message="auth failed")
    downloads = _downloads()
    downloads[0] = StoreResult("App Store", error_message="timeout")
    msg = format_combined(downloads, rev, NOW)
    assert msg.count("unavailable") == 2
    assert "2 / 8,204" in msg and "₱86 / ₱171" in msg


# ----- entry point -----

def _config():
    cfg = MagicMock()
    cfg.timezone = "Asia/Manila"
    return cfg


@patch("src.daily.send_telegram_message", return_value=True)
@patch("src.daily.collect_daily", side_effect=RuntimeError("revenue down"))
@patch("src.daily.collect_downloads", return_value=_downloads())
@patch("src.daily.load_config")
def test_daily_sends_once_even_if_one_half_fails(mock_cfg, _dl, _rev, mock_send):
    from src.daily import main

    mock_cfg.return_value = _config()
    code = main([])

    mock_send.assert_called_once()
    sent = mock_send.call_args[0][1]
    assert "2 / 9,109" in sent and "unavailable" in sent
    assert code == 1  # sent, but the run is flagged red


@patch("src.daily.send_telegram_message")
@patch("src.daily.collect_daily", side_effect=RuntimeError("down"))
@patch("src.daily.collect_downloads", side_effect=RuntimeError("down"))
@patch("src.daily.load_config")
def test_daily_skips_send_when_both_halves_fail(mock_cfg, _dl, _rev, mock_send):
    from src.daily import main

    mock_cfg.return_value = _config()
    assert main([]) == 1
    mock_send.assert_not_called()


@patch("src.daily.send_telegram_message", return_value=True)
@patch("src.daily.collect_daily", return_value=_revenue())
@patch("src.daily.collect_downloads", return_value=_downloads())
@patch("src.daily.load_config")
def test_daily_success_exits_zero(mock_cfg, _dl, _rev, mock_send):
    from src.daily import main

    mock_cfg.return_value = _config()
    assert main([]) == 0
    mock_send.assert_called_once()
