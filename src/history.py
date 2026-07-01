"""CSV persistence layer for daily download history.

Appends download data to data/downloads.csv for historical tracking
and dashboard visualization.
"""

import csv
import logging
import os
import tempfile
from datetime import date, datetime
from typing import Optional

from src.stores.base import StoreResult

logger = logging.getLogger(__name__)

CSV_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CSV_PATH = os.path.join(CSV_DIR, "downloads.csv")
CSV_HEADERS = ["date", "report_date", "platform", "daily_downloads", "cumulative_total"]

PLATFORM_MAP = {
    "App Store": "appstore",
    "Google Play": "googleplay",
}


def _parse_data_date(data_date_str: str) -> Optional[str]:
    """Convert store data date (e.g. 'Feb 11') to YYYY-MM-DD.

    Assumes current year. If the parsed date is in the future,
    falls back to previous year.

    Args:
        data_date_str: Date string like 'Feb 11' or 'Jan 03'.

    Returns:
        ISO date string (YYYY-MM-DD) or None if parsing fails.
    """
    if not data_date_str:
        return None
    try:
        today = date.today()
        parsed = datetime.strptime(data_date_str.strip(), "%b %d").replace(year=today.year).date()
        if parsed > today:
            parsed = parsed.replace(year=today.year - 1)
        return parsed.isoformat()
    except ValueError:
        # Try YYYY-MM-DD format directly
        try:
            return date.fromisoformat(data_date_str.strip()).isoformat()
        except ValueError:
            logger.warning("Could not parse data date: %s", data_date_str)
            return None


def _load_existing_keys() -> set[tuple[str, str]]:
    """Load existing (report_date, platform) pairs from CSV.

    Returns:
        Set of (report_date, platform) tuples already recorded.
    """
    keys: set[tuple[str, str]] = set()
    if not os.path.exists(CSV_PATH):
        return keys
    try:
        with open(CSV_PATH, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                keys.add((row["report_date"], row["platform"]))
    except (KeyError, csv.Error) as e:
        logger.warning("Error reading existing CSV: %s", e)
    return keys


def _ensure_csv_exists() -> None:
    """Create data directory and CSV file with headers if they don't exist."""
    os.makedirs(CSV_DIR, exist_ok=True)
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)
        logger.info("Created %s with headers", CSV_PATH)


def save_to_history(results: list[StoreResult], cumulative: dict) -> None:
    """Append download results to the CSV history file.

    Idempotent: skips rows where (report_date, platform) already exists.

    Args:
        results: List of StoreResult from each store client.
        cumulative: Dict with cumulative totals keyed by 'apple' and 'google_play'.
    """
    _ensure_csv_exists()
    existing_keys = _load_existing_keys()
    today_str = date.today().isoformat()

    rows_to_write: list[list] = []

    for result in results:
        if result.daily_downloads is None:
            logger.info("Skipping %s — no daily downloads data", result.store_name)
            continue

        platform = PLATFORM_MAP.get(result.store_name)
        if not platform:
            logger.warning("Unknown store name: %s", result.store_name)
            continue

        report_date = _parse_data_date(result.data_date) if result.data_date else None
        if not report_date:
            logger.warning("Skipping %s — could not parse data date '%s'", result.store_name, result.data_date)
            continue

        if (report_date, platform) in existing_keys:
            logger.info("Skipping %s %s — already recorded", platform, report_date)
            continue

        cum_key = "apple" if platform == "appstore" else "google_play"
        cumulative_total = cumulative.get(cum_key, 0)

        rows_to_write.append([
            today_str,
            report_date,
            platform,
            result.daily_downloads,
            cumulative_total,
        ])

    if not rows_to_write:
        logger.info("No new rows to write to history CSV")
        return

    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows_to_write)

    logger.info("Wrote %d row(s) to %s", len(rows_to_write), CSV_PATH)


def reconcile_history_rows(reports: list[StoreResult]) -> Optional[dict[str, int]]:
    """Reconcile CSV history against freshly fetched daily values.

    Store exports (esp. Google Play's GCS export) can stall and then backfill
    several days at once. A run only fetches a single "newest" date, so those
    intermediate days would otherwise never be recorded — undercounting the
    cumulative. This reconciles the CSV against a multi-day fetch:
      - inserts any missing (report_date, platform) days, and
      - corrects existing rows whose daily value changed (retroactive updates),
    then rebuilds the cumulative running total per platform in date order.

    Args:
        reports: List of StoreResult with freshly fetched daily values,
            typically spanning the last N days per platform.

    Returns:
        Dict with updated cumulative totals by key ('apple'/'google_play'),
        or None if nothing changed.
    """
    if not os.path.exists(CSV_PATH):
        return None

    # Build fetched map: (report_date, platform) -> daily_downloads
    fetched: dict[tuple[str, str], int] = {}
    for result in reports:
        if result.daily_downloads is None:
            continue
        platform = PLATFORM_MAP.get(result.store_name)
        if not platform:
            continue
        report_date = _parse_data_date(result.data_date) if result.data_date else None
        if not report_date:
            continue
        fetched[(report_date, platform)] = result.daily_downloads

    if not fetched:
        return None

    # Read existing CSV
    rows: list[dict[str, str]] = []
    with open(CSV_PATH, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))

    existing_keys = {(row["report_date"], row["platform"]) for row in rows}

    # Capture each platform's base offset (total before its earliest day) from
    # the EXISTING rows, before any inserts. Deriving the base later from a
    # freshly inserted row would use its placeholder cumulative and corrupt the
    # running total, so it must be pinned to real historical data here.
    platform_bases = _platform_bases(rows)

    today_str = date.today().isoformat()
    changed = False

    # Correct existing rows whose daily value differs
    for row in rows:
        key = (row["report_date"], row["platform"])
        if key in fetched and int(row["daily_downloads"]) != fetched[key]:
            logger.info(
                "Correcting %s %s: daily %s -> %d",
                key[1], key[0], row["daily_downloads"], fetched[key],
            )
            row["daily_downloads"] = str(fetched[key])
            changed = True

    # Insert missing days (cumulative filled in during recompute below)
    for (report_date, platform), daily in fetched.items():
        if (report_date, platform) not in existing_keys:
            logger.info("Backfilling missing %s %s: daily %d", platform, report_date, daily)
            rows.append({
                "date": today_str,
                "report_date": report_date,
                "platform": platform,
                "daily_downloads": str(daily),
                "cumulative_total": "0",
            })
            changed = True

    if not changed:
        return None

    # Rewrite in report_date order so the latest row per platform lands at the
    # tail (the dashboard reads it positionally) and the running sum is coherent.
    rows.sort(key=lambda r: r["report_date"])
    updated_totals = _rebuild_cumulative(rows, platform_bases)
    _write_history(rows)

    logger.info("Reconciled CSV history (inserts + corrections)")
    return updated_totals


def _platform_bases(rows: list[dict[str, str]]) -> dict[str, int]:
    """Base offset per platform: the cumulative total before its earliest day."""
    bases: dict[str, int] = {}
    for row in sorted(rows, key=lambda r: r["report_date"]):
        platform = row["platform"]
        if platform not in bases:
            bases[platform] = int(row["cumulative_total"]) - int(row["daily_downloads"])
    return bases


def _rebuild_cumulative(
    rows: list[dict[str, str]], platform_bases: dict[str, int]
) -> dict[str, int]:
    """Recompute the cumulative running total per platform.

    ``rows`` must already be sorted by ``report_date``. Each platform's running
    sum starts from its supplied base (0 for a platform with no prior rows), so
    the pre-history offset is preserved even when older days are backfilled.
    Mutates each row's ``cumulative_total`` and returns the final total per
    cumulative key ('apple'/'google_play').
    """
    platform_rows: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        platform_rows.setdefault(row["platform"], []).append(row)

    updated_totals: dict[str, int] = {}
    for platform, p_rows in platform_rows.items():
        running = platform_bases.get(platform, 0)
        for row in p_rows:
            running += int(row["daily_downloads"])
            row["cumulative_total"] = str(running)
        cum_key = "apple" if platform == "appstore" else "google_play"
        updated_totals[cum_key] = running

    return updated_totals


def _write_history(rows: list[dict[str, str]]) -> None:
    """Atomically rewrite the history CSV (temp file + os.replace).

    The reconcile path rewrites the whole file, so a crash mid-write would
    corrupt the single source of truth; the swap makes it all-or-nothing.
    """
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(CSV_PATH), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, CSV_PATH)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def get_latest_per_platform() -> dict[str, dict]:
    """Read the latest row per platform from CSV.

    Returns:
        Dict keyed by platform ('appstore', 'googleplay') with
        'daily_downloads', 'cumulative_total', and 'report_date'.
    """
    if not os.path.exists(CSV_PATH):
        return {}

    latest: dict[str, dict] = {}
    try:
        with open(CSV_PATH, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                platform = row["platform"]
                # Keep the row with the greatest report_date — robust to rows
                # being appended/backfilled out of chronological order.
                if platform in latest and row["report_date"] <= latest[platform]["report_date"]:
                    continue
                latest[platform] = {
                    "daily_downloads": int(row["daily_downloads"]),
                    "cumulative_total": int(row["cumulative_total"]),
                    "report_date": row["report_date"],
                }
    except (KeyError, csv.Error, ValueError) as e:
        logger.warning("Error reading CSV for latest data: %s", e)

    return latest
