"""Tests for the CSV reconcile / cumulative-rebuild logic in src.history."""

import csv

import pytest

from src import history
from src.stores.base import StoreResult

HEADERS = ["date", "report_date", "platform", "daily_downloads", "cumulative_total"]


@pytest.fixture
def csv_path(tmp_path, monkeypatch):
    """Point history at a throwaway CSV for the duration of a test."""
    path = tmp_path / "downloads.csv"
    monkeypatch.setattr(history, "CSV_PATH", str(path))
    return path


def _write(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        w.writerows(rows)


def _read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _gp(date_str, daily):
    from datetime import datetime
    return StoreResult(
        store_name="Google Play",
        daily_downloads=daily,
        data_date=datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d"),
    )


def test_inserts_missing_middle_days(csv_path):
    # GP recorded through Jun 17, then the export un-stalls and publishes Jun 18-20.
    _write(csv_path, [
        ["2025-11-01", "2025-11-01", "googleplay", "0", "0"],
        ["2026-06-22", "2026-06-17", "googleplay", "13", "13"],
    ])
    reports = [_gp("2026-06-17", 13), _gp("2026-06-18", 5),
               _gp("2026-06-19", 3), _gp("2026-06-20", 4)]

    totals = history.reconcile_history_rows(reports)

    gp = [r for r in _read(csv_path) if r["platform"] == "googleplay"]
    dates = [r["report_date"] for r in gp]
    assert dates == sorted(dates) and len(dates) == len(set(dates))  # sorted, unique
    assert "2026-06-18" in dates and "2026-06-20" in dates  # backfilled
    cums = [int(r["cumulative_total"]) for r in gp]
    assert cums == sorted(cums)  # monotonic
    assert int(gp[-1]["cumulative_total"]) == 0 + 13 + 5 + 3 + 4  # base 0 + all dailies
    assert totals["google_play"] == 25
    assert history.get_latest_per_platform()["googleplay"]["report_date"] == "2026-06-20"


def test_preserves_base_offset_on_early_insert(csv_path):
    # Earliest existing row carries a pre-history offset (base 150).
    _write(csv_path, [
        ["2026-06-10", "2026-06-05", "googleplay", "10", "160"],  # base = 160 - 10 = 150
        ["2026-06-12", "2026-06-07", "googleplay", "2", "162"],
    ])
    # A backfill arrives for a day EARLIER than the earliest existing row.
    totals = history.reconcile_history_rows([_gp("2026-06-04", 7)])

    gp = [r for r in _read(csv_path) if r["platform"] == "googleplay"]
    by_date = {r["report_date"]: int(r["cumulative_total"]) for r in gp}
    # Base 150 must survive: Jun04 = 150+7, Jun05 = +10, Jun07 = +2
    assert by_date["2026-06-04"] == 157
    assert by_date["2026-06-05"] == 167
    assert by_date["2026-06-07"] == 169
    assert totals["google_play"] == 169


def test_corrects_existing_daily(csv_path):
    _write(csv_path, [
        ["2025-11-01", "2025-11-01", "googleplay", "0", "0"],
        ["2026-06-22", "2026-06-17", "googleplay", "13", "13"],
    ])
    # GCS retroactively revised Jun 17 from 13 -> 20.
    totals = history.reconcile_history_rows([_gp("2026-06-17", 20)])
    gp = [r for r in _read(csv_path) if r["platform"] == "googleplay"]
    assert gp[-1]["daily_downloads"] == "20"
    assert int(gp[-1]["cumulative_total"]) == 20
    assert totals["google_play"] == 20


def test_idempotent_no_change_returns_none(csv_path):
    _write(csv_path, [
        ["2025-11-01", "2025-11-01", "googleplay", "0", "0"],
        ["2026-06-22", "2026-06-17", "googleplay", "13", "13"],
    ])
    # Same data already present -> nothing changes.
    assert history.reconcile_history_rows([_gp("2026-06-17", 13)]) is None


def test_does_not_touch_other_platform(csv_path):
    _write(csv_path, [
        ["2026-06-28", "2026-06-27", "appstore", "8", "500"],
        ["2026-06-29", "2026-06-28", "appstore", "2", "502"],
        ["2026-06-22", "2026-06-17", "googleplay", "13", "13"],
    ])
    history.reconcile_history_rows([_gp("2026-06-18", 5)])
    appstore = [r for r in _read(csv_path) if r["platform"] == "appstore"]
    # App Store cumulative recomputed from its own base, values unchanged.
    assert [r["cumulative_total"] for r in appstore] == ["500", "502"]
