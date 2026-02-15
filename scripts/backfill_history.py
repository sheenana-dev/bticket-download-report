"""Backfill historical download data from App Store and Google Play.

Fetches daily data from a start date to the earliest date in the existing CSV,
then prepends it to create a complete history.
"""

import csv
import os
import sys
from datetime import date, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.config import load_config
from src.stores.apple import AppleStoreClient
from src.stores.google_play import GooglePlayClient
from src.utils.logger import setup_logging

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "downloads.csv")
CSV_HEADERS = ["date", "report_date", "platform", "daily_downloads", "cumulative_total"]

START_DATE = date(2025, 11, 1)


def get_earliest_csv_date() -> date:
    """Find the earliest report_date in the existing CSV."""
    if not os.path.exists(CSV_PATH):
        return date.today()
    with open(CSV_PATH, "r", newline="") as f:
        reader = csv.DictReader(f)
        dates = []
        for row in reader:
            try:
                dates.append(date.fromisoformat(row["report_date"]))
            except (ValueError, KeyError):
                pass
    return min(dates) if dates else date.today()


def load_existing_csv() -> list[dict]:
    """Load all rows from the existing CSV."""
    rows = []
    if not os.path.exists(CSV_PATH):
        return rows
    with open(CSV_PATH, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def main():
    logger = setup_logging()
    logger.info("Starting historical backfill")

    try:
        config = load_config()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    earliest = get_earliest_csv_date()
    logger.info("Existing CSV starts at: %s", earliest)
    logger.info("Backfilling from: %s to %s", START_DATE, earliest - timedelta(days=1))

    if START_DATE >= earliest:
        logger.info("No backfill needed — CSV already starts at or before %s", START_DATE)
        return

    apple_client = AppleStoreClient(config.apple)
    google_client = GooglePlayClient(config.google_play)

    # Pre-download Google Play monthly CSVs to avoid repeated GCS calls
    gp_csv_cache: dict[str, str | None] = {}
    backfill_rows: list[dict] = []

    current = START_DATE
    end_date = earliest  # exclusive

    while current < end_date:
        date_str = current.isoformat()
        logger.info("Fetching data for %s ...", date_str)

        # Apple App Store — fetch EXACT date only, no fallback
        apple_daily = 0
        try:
            data = apple_client._fetch_sales_report(current)
            apple_daily = apple_client._parse_tsv(data)
            logger.info("  Apple: %d downloads", apple_daily)
        except Exception as e:
            # 404 = no report for this date, which is normal (weekends, holidays)
            logger.info("  Apple: no report for %s (%s)", date_str, type(e).__name__)

        backfill_rows.append({
            "date": date_str,
            "report_date": date_str,
            "platform": "appstore",
            "daily_downloads": str(apple_daily),
            "cumulative_total": "0",  # will recalculate
        })

        # Google Play
        gp_daily = 0
        try:
            year_month = current.strftime("%Y%m")
            if year_month not in gp_csv_cache:
                gp_csv_cache[year_month] = google_client._download_csv(year_month)

            csv_text = gp_csv_cache[year_month]
            if csv_text:
                daily = google_client._parse_csv(csv_text, current)
                if daily is not None:
                    gp_daily = daily
                    logger.info("  Google Play: %d downloads", gp_daily)
                else:
                    logger.info("  Google Play: no data for this date")
            else:
                logger.info("  Google Play: no CSV for %s", year_month)
        except Exception as e:
            logger.warning("  Google Play fetch failed for %s: %s", date_str, e)

        backfill_rows.append({
            "date": date_str,
            "report_date": date_str,
            "platform": "googleplay",
            "daily_downloads": str(gp_daily),
            "cumulative_total": "0",  # will recalculate
        })

        current += timedelta(days=1)

    if not backfill_rows:
        logger.info("No backfill rows generated")
        return

    # Load existing rows
    existing_rows = load_existing_csv()
    logger.info("Existing CSV has %d rows", len(existing_rows))

    # Combine: backfill first, then existing
    all_rows = backfill_rows + existing_rows

    # Recalculate cumulative totals per platform
    platform_running: dict[str, int] = {}
    for row in all_rows:
        p = row["platform"]
        daily = int(row["daily_downloads"])
        if p not in platform_running:
            platform_running[p] = 0
        platform_running[p] += daily
        row["cumulative_total"] = str(platform_running[p])

    # Write combined CSV
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(all_rows)

    logger.info("Wrote %d total rows to %s", len(all_rows), CSV_PATH)
    logger.info("Final totals — App Store: %s, Google Play: %s",
                platform_running.get("appstore", 0),
                platform_running.get("googleplay", 0))


if __name__ == "__main__":
    main()
