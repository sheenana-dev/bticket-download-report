import csv
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.stores.apple import AppleStoreClient
from src.stores.base import StoreResult
from src.stores.google_play import GooglePlayClient
from src.history import save_to_history, reconcile_history_rows, CSV_PATH
from src.report import build_report_results
from src.utils.logger import setup_logging

CACHE_FILE = "cumulative_totals.json"

# Same name setup_logging() returns, so log lines read "download_report: ...".
logger = logging.getLogger("download_report")


def load_cumulative_totals() -> dict:
    """Load cached cumulative totals from file."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {"apple": 440, "google_play": 165, "apple_last_date": "Feb 16", "google_play_last_date": "Feb 14"}


def save_cumulative_totals(totals: dict):
    """Save updated cumulative totals for next run."""
    with open(CACHE_FILE, "w") as f:
        json.dump(totals, f, indent=2)


def _parse_short_date(s: str) -> Optional[date]:
    """Parse 'Feb 14' format to a date (assumes current or previous year)."""
    if not s:
        return None
    # Strip suffixes like " (delayed)"
    clean = s.split("(")[0].strip()
    try:
        dt = datetime.strptime(clean, "%b %d")
        now = datetime.now()
        result = dt.replace(year=now.year)
        # If parsed date is far in the future, it was probably last year
        if result.date() > now.date() + timedelta(days=30):
            result = result.replace(year=now.year - 1)
        return result.date()
    except (ValueError, TypeError):
        return None


def _is_newer_date(fetched: str, last: Optional[str]) -> bool:
    """Return True if fetched data_date is strictly after last recorded date."""
    if not last:
        return True
    fetched_d = _parse_short_date(fetched)
    last_d = _parse_short_date(last)
    if fetched_d is None or last_d is None:
        # Can't compare — fall back to != check to avoid silent drops
        return fetched != last
    return fetched_d > last_d


def _backfill_google_play(data_str: str) -> None:
    """Manually backfill Google Play data from Play Console UI.

    Args:
        data_str: Comma-separated date:downloads pairs, e.g.
                  "2026-02-15:3,2026-02-16:2,2026-02-17:1"
    """
    logger = setup_logging()
    logger.info("Starting Google Play manual backfill")

    cumulative = load_cumulative_totals()
    existing_keys = set()
    rows = []

    # Read existing CSV
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
                existing_keys.add((row["report_date"], row["platform"]))

    # Parse input
    today_str = date.today().isoformat()
    entries = [e.strip() for e in data_str.split(",") if e.strip()]
    new_rows = []
    for entry in entries:
        parts = entry.split(":")
        if len(parts) != 2:
            logger.warning("Skipping invalid entry: %s", entry)
            continue
        report_date, daily_str = parts[0].strip(), parts[1].strip()
        try:
            date.fromisoformat(report_date)
            daily = int(daily_str)
        except (ValueError, TypeError):
            logger.warning("Skipping invalid entry: %s", entry)
            continue

        if (report_date, "googleplay") in existing_keys:
            logger.info("Skipping %s — already in CSV", report_date)
            continue

        cumulative["google_play"] = cumulative.get("google_play", 0) + daily
        cumulative["google_play_last_date"] = datetime.strptime(report_date, "%Y-%m-%d").strftime("%b %d")

        new_rows.append({
            "date": today_str,
            "report_date": report_date,
            "platform": "googleplay",
            "daily_downloads": str(daily),
            "cumulative_total": str(cumulative["google_play"]),
        })
        existing_keys.add((report_date, "googleplay"))
        logger.info("Adding Google Play %s: %d downloads (cumulative: %d)",
                     report_date, daily, cumulative["google_play"])

    if not new_rows:
        logger.info("No new rows to backfill")
        return

    # Append to CSV
    headers = ["date", "report_date", "platform", "daily_downloads", "cumulative_total"]
    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writerows(new_rows)

    # Save cumulative totals
    cumulative["last_updated"] = datetime.now().isoformat()
    save_cumulative_totals(cumulative)

    logger.info("Backfilled %d Google Play row(s)", len(new_rows))


def _fetch_with_cumulative(client, key: str, target: date, cumulative: dict) -> StoreResult:
    """Fetch T-1 data; add to the running total only when the data date is new
    (so consecutive runs on the same store date don't double-count)."""
    result = client.fetch_report(target_date=target)
    last_key = f"{key}_last_date"
    if result.daily_downloads is not None and _is_newer_date(result.data_date, cumulative.get(last_key)):
        cumulative[key] = cumulative.get(key, 0) + result.daily_downloads
        cumulative[last_key] = result.data_date
    total = cumulative.get(key, 0)
    result.total_downloads = total if total > 0 else None
    return result


def _reconcile_google(google_client: GooglePlayClient, target: date, cumulative: dict) -> None:
    """Re-fetch 30 days of Google Play to backfill stalled days and correct
    retroactive GCS updates (the export can freeze then publish several days at
    once). Monthly CSVs are cached per month, so the wide window is cheap."""
    try:
        recent_gp = google_client.fetch_recent_reports(target_date=target, lookback_days=30)
        reconciled = reconcile_history_rows(recent_gp) if recent_gp else None
        if reconciled:
            cumulative.update(reconciled)
            save_cumulative_totals(cumulative)
            logger.info("Reconciled Google Play history (backfill + corrections)")
    except Exception as e:
        logger.warning("Google Play reconciliation failed (non-fatal): %s", e)


def _google_churn(google_client: GooglePlayClient, target: date) -> dict:
    """Uninstalls are sourced live from the export, not the CSV; never fatal."""
    try:
        daily_un, total_un = google_client.fetch_churn(target)
        return {"Google Play": (daily_un, total_un)} if total_un is not None else {}
    except Exception as e:
        logger.warning("Churn fetch failed (non-fatal): %s", e)
        return {}


def collect_downloads(config, now: datetime) -> list[StoreResult]:
    """Fetch, persist and reconcile download data; return per-store results.

    Results are built from the CSV (single source of truth, matches the
    dashboard), falling back to this run's API results for a platform not yet
    in the CSV. Does not send anything.
    """
    yesterday = (now - timedelta(days=1)).date()
    logger.info("Report date: %s, target data date: %s", now.date(), yesterday)

    cumulative = load_cumulative_totals()
    google_client = GooglePlayClient(config.google_play)
    results = [
        _fetch_with_cumulative(AppleStoreClient(config.apple), "apple", yesterday, cumulative),
        _fetch_with_cumulative(google_client, "google_play", yesterday, cumulative),
    ]
    cumulative["last_updated"] = now.isoformat()
    save_cumulative_totals(cumulative)

    try:
        save_to_history(results, cumulative)
        logger.info("Download history saved to CSV")
    except Exception as e:
        logger.warning("Failed to save history CSV (non-fatal): %s", e)

    _reconcile_google(google_client, yesterday, cumulative)
    return build_report_results(now, fallback=results, churn=_google_churn(google_client, yesterday))


def main():
    dry_run = "--dry-run" in sys.argv

    # Handle manual Google Play backfill
    for arg in sys.argv:
        if arg.startswith("--backfill-gp="):
            _backfill_google_play(arg.split("=", 1)[1])
            return
    backfill_idx = None
    for i, arg in enumerate(sys.argv):
        if arg == "--backfill-gp" and i + 1 < len(sys.argv):
            backfill_idx = i
            break
    if backfill_idx is not None:
        _backfill_google_play(sys.argv[backfill_idx + 1])
        return

    # The standalone download message was replaced by the combined daily report;
    # keep `python -m src.main` working as an alias so nothing sends the old format.
    from src.daily import main as daily_main  # local import: src.daily imports this module
    sys.exit(daily_main(["--dry-run"] if dry_run else []))


if __name__ == "__main__":
    main()
