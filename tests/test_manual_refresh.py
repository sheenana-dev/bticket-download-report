"""Tests for parsing + merging manual Google Play figures (src.manual_refresh)."""

import csv
from datetime import date

import pytest

from src import history, manual_refresh

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


# ----- date parsing -----

@pytest.mark.parametrize("text,expected", [
    ("2026-06-18", date(2026, 6, 18)),
    ("Jul 2, 2026", date(2026, 7, 2)),
    ("July 2, 2026", date(2026, 7, 2)),
    ("06/18/2026", date(2026, 6, 18)),
    ("  2026-06-18  ", date(2026, 6, 18)),
])
def test_parse_date_formats(text, expected):
    assert manual_refresh.parse_date(text) == expected


def test_parse_date_rejects_garbage():
    assert manual_refresh.parse_date("not a date") is None
    assert manual_refresh.parse_date("") is None


# ----- pairs -----

def test_parse_pairs_basic():
    assert manual_refresh.parse_pairs("2026-06-18:149, 2026-06-19:153") == {
        date(2026, 6, 18): 149,
        date(2026, 6, 19): 153,
    }


def test_parse_pairs_rejects_bad_chunk():
    with pytest.raises(ValueError):
        manual_refresh.parse_pairs("2026-06-18")


# ----- csv (Play Console shape) -----

PLAY_CSV = (
    "Date,All countries / regions,Philippines\n"
    "2026-06-18,149,148\n"
    "2026-06-19,153,153\n"
    "2026-06-20,-,-\n"           # dash -> skipped
)


def test_parse_csv_defaults_to_first_data_column():
    assert manual_refresh.parse_csv(PLAY_CSV) == {
        date(2026, 6, 18): 149,
        date(2026, 6, 19): 153,
    }


def test_parse_csv_named_column():
    assert manual_refresh.parse_csv(PLAY_CSV, column="Philippines") == {
        date(2026, 6, 18): 148,
        date(2026, 6, 19): 153,
    }


def test_parse_csv_missing_column_raises():
    with pytest.raises(ValueError):
        manual_refresh.parse_csv(PLAY_CSV, column="Nope")


def test_parse_csv_handles_quoted_commas():
    # A real export quotes comma-bearing dates/values ("Jul 2, 2026", "1,257").
    text = 'Date,All countries / regions\n"Jul 2, 2026","1,257"\n'
    assert manual_refresh.parse_csv(text) == {date(2026, 7, 2): 1257}


# ----- apply (integration through reconcile) -----

def test_apply_google_refresh_backfills_and_rebuilds_cumulative(csv_path):
    # Seed: Google frozen at Jun 17 with cumulative 472.
    _write(csv_path, [["2026-06-22", "2026-06-17", "googleplay", "13", "472"]])

    updated = manual_refresh.apply_google_refresh({
        date(2026, 6, 18): 149,
        date(2026, 6, 19): 153,
    })

    assert updated["google_play"] == 472 + 149 + 153  # 774
    rows = {r["report_date"]: r for r in _read(csv_path) if r["platform"] == "googleplay"}
    assert rows["2026-06-18"]["cumulative_total"] == "621"
    assert rows["2026-06-19"]["cumulative_total"] == "774"


def test_apply_google_refresh_noop_when_unchanged(csv_path):
    _write(csv_path, [["2026-06-22", "2026-06-17", "googleplay", "13", "472"]])
    assert manual_refresh.apply_google_refresh({date(2026, 6, 17): 13}) is None
