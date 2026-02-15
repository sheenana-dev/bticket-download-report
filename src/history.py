"""CSV persistence layer for daily download history.

Appends download data to data/downloads.csv for historical tracking
and dashboard visualization.
"""

import csv
import logging
import os
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


def correct_history_rows(corrections: list[StoreResult]) -> Optional[dict[str, int]]:
    """Update existing CSV rows with corrected daily download values.

    GCS data gets retroactively updated. This compares fresh values against
    existing CSV rows and corrects any differences, then recalculates
    cumulative totals for affected platforms.

    Args:
        corrections: List of StoreResult with freshly fetched daily values.

    Returns:
        Dict with updated cumulative totals by key ('apple'/'google_play'),
        or None if no corrections were needed.
    """
    if not os.path.exists(CSV_PATH):
        return None

    # Build correction map: (report_date, platform) -> daily_downloads
    correction_map: dict[tuple[str, str], int] = {}
    for result in corrections:
        if result.daily_downloads is None:
            continue
        platform = PLATFORM_MAP.get(result.store_name)
        if not platform:
            continue
        report_date = _parse_data_date(result.data_date) if result.data_date else None
        if not report_date:
            continue
        correction_map[(report_date, platform)] = result.daily_downloads

    if not correction_map:
        return None

    # Read existing CSV
    rows: list[dict] = []
    with open(CSV_PATH, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))

    # Calculate base per platform BEFORE applying corrections
    platform_bases: dict[str, int] = {}
    for row in rows:
        p = row["platform"]
        if p not in platform_bases:
            platform_bases[p] = int(row["cumulative_total"]) - int(row["daily_downloads"])

    # Apply corrections
    changed = False
    for row in rows:
        key = (row["report_date"], row["platform"])
        if key in correction_map:
            new_daily = correction_map[key]
            old_daily = int(row["daily_downloads"])
            if old_daily != new_daily:
                logger.info(
                    "Correcting %s %s: daily %d -> %d",
                    key[1], key[0], old_daily, new_daily,
                )
                row["daily_downloads"] = str(new_daily)
                changed = True

    if not changed:
        return None

    # Recalculate cumulative totals per platform
    platform_rows: dict[str, list[dict]] = {}
    for row in rows:
        p = row["platform"]
        if p not in platform_rows:
            platform_rows[p] = []
        platform_rows[p].append(row)

    updated_totals: dict[str, int] = {}
    for platform, p_rows in platform_rows.items():
        base = platform_bases.get(platform, 0)
        running = base
        for row in p_rows:
            running += int(row["daily_downloads"])
            row["cumulative_total"] = str(running)
        cum_key = "apple" if platform == "appstore" else "google_play"
        updated_totals[cum_key] = running

    # Rewrite CSV
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Applied retroactive corrections to CSV history")
