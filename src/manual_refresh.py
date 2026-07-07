"""Merge manually-sourced Google Play daily installs into the CSV history.

Used when Google's GCS bulk export is frozen (Google-side) but the Play Console
UI still shows current numbers (e.g. "device acquisition"). Values are merged via
the same ``reconcile_history_rows`` path the daily report uses, so:
  - cumulative totals are rebuilt coherently in date order, and
  - if/when Google's export resumes, the daily reconcile overwrites these manual
    values with Google's official figures automatically (self-healing).

Input parsing lives here (pure, testable); the CLI wrapper is
``scripts/refresh_google_play.py``.
"""

import csv
import io
from datetime import date, datetime
from typing import Optional

from src.history import reconcile_history_rows
from src.stores.base import StoreResult

# Accepted date formats, widest-to-narrowest. Formats without a year assume the
# current year (rolled back if that lands in the future).
_DATE_FORMATS = ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%b %d", "%B %d")

_EMPTY = {"", "-", "—", "–", "n/a"}


def parse_date(value: str) -> Optional[date]:
    """Parse a date from any of the accepted formats, or None."""
    value = value.strip()
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt:
            dt = dt.replace(year=date.today().year)
            if dt.date() > date.today():
                dt = dt.replace(year=dt.year - 1)
        return dt.date()
    return None


def _to_int(value: str) -> Optional[int]:
    """Parse an install count (tolerates commas, blanks, dashes)."""
    value = value.strip().replace(",", "")
    if value.lower() in _EMPTY:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def parse_pairs(text: str) -> dict[date, int]:
    """Parse ``DATE:COUNT`` pairs, e.g. ``"2026-06-18:149,2026-06-19:153"``."""
    result: dict[date, int] = {}
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise ValueError(f"Expected DATE:COUNT, got {chunk!r}")
        date_str, count_str = chunk.rsplit(":", 1)
        parsed_date = parse_date(date_str)
        count = _to_int(count_str)
        if parsed_date is None or count is None:
            raise ValueError(f"Could not parse pair {chunk!r}")
        result[parsed_date] = count
    return result


def parse_csv(text: str, column: Optional[str] = None) -> dict[date, int]:
    """Parse a Play Console CSV export into {date: daily installs}.

    Auto-detects the date column (header contains "date"/"day"). Uses ``column``
    for the count if given, else the first non-date, non-percentage column
    (Play Console's default first data column is "All countries / regions").
    """
    reader = csv.DictReader(io.StringIO(text))
    fields = [f for f in (reader.fieldnames or []) if f]
    if not fields:
        raise ValueError("CSV has no header row")

    date_col = next((f for f in fields if "date" in f.lower() or "day" in f.lower()), None)
    if date_col is None:
        raise ValueError(f"No date column found; columns: {fields}")

    if column:
        value_col = next((f for f in fields if f.strip().lower() == column.strip().lower()), None)
        if value_col is None:
            raise ValueError(f"Column {column!r} not found; columns: {fields}")
    else:
        value_col = next(
            (f for f in fields if f != date_col and "percentage" not in f.lower()), None
        )
        if value_col is None:
            raise ValueError(f"No value column found; columns: {fields}")

    result: dict[date, int] = {}
    for row in reader:
        parsed_date = parse_date(row.get(date_col, ""))
        count = _to_int(row.get(value_col, ""))
        if parsed_date is not None and count is not None:
            result[parsed_date] = count
    return result


def apply_google_refresh(daily: dict[date, int]) -> Optional[dict[str, int]]:
    """Merge daily Google Play installs into the CSV; return updated totals.

    Returns the reconcile result (cumulative totals by key) or None if the CSV
    already matched the given values.
    """
    results = [
        StoreResult(
            store_name="Google Play",
            daily_downloads=count,
            data_date=day.isoformat(),
        )
        for day, count in sorted(daily.items())
    ]
    return reconcile_history_rows(results)
