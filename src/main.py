import json
import os
import sys
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.config import load_config
from src.formatter import format_report
from src.stores.apple import AppleStoreClient
from src.stores.google_play import GooglePlayClient
from src.history import save_to_history, correct_history_rows
from src.telegram import send_telegram_message
from src.utils.logger import setup_logging

CACHE_FILE = "cumulative_totals.json"


def load_cumulative_totals() -> dict:
    """Load cached cumulative totals from file."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {"apple": 359, "google_play": 166, "apple_last_date": "Feb 14", "google_play_last_date": "Feb 14"}


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


def main():
    logger = setup_logging()
    logger.info("Starting B-Ticket Daily Download Report generation")

    try:
        config = load_config()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    pht = ZoneInfo(config.timezone)
    now = datetime.now(pht)
    yesterday = (now - timedelta(days=1)).date()

    logger.info("Report date: %s, target data date: %s", now.date(), yesterday)

    cumulative = load_cumulative_totals()
    results = []

    # Apple App Store (T-1 data)
    # Track last fetched date to avoid double-counting on consecutive runs
    logger.info("Fetching Apple App Store data...")
    apple_client = AppleStoreClient(config.apple)
    apple_result = apple_client.fetch_report(target_date=yesterday)
    if apple_result.daily_downloads is not None:
        last_apple_date = cumulative.get("apple_last_date")
        if _is_newer_date(apple_result.data_date, last_apple_date):
            cumulative["apple"] = cumulative.get("apple", 0) + apple_result.daily_downloads
            cumulative["apple_last_date"] = apple_result.data_date
    apple_total = cumulative.get("apple", 0)
    apple_result.total_downloads = apple_total if apple_total > 0 else None
    results.append(apple_result)

    # Google Play (up to 5-day delay, cumulative tracked locally)
    # Track last fetched date to avoid double-counting on consecutive runs
    logger.info("Fetching Google Play data...")
    google_client = GooglePlayClient(config.google_play)
    google_result = google_client.fetch_report(target_date=yesterday)
    if google_result.daily_downloads is not None:
        last_gp_date = cumulative.get("google_play_last_date")
        if _is_newer_date(google_result.data_date, last_gp_date):
            cumulative["google_play"] = cumulative.get("google_play", 0) + google_result.daily_downloads
            cumulative["google_play_last_date"] = google_result.data_date
    gp_total = cumulative.get("google_play", 0)
    google_result.total_downloads = gp_total if gp_total > 0 else None
    results.append(google_result)

    # Save cumulative totals
    cumulative["last_updated"] = now.isoformat()
    save_cumulative_totals(cumulative)

    # Persist to CSV history
    try:
        save_to_history(results, cumulative)
        logger.info("Download history saved to CSV")
    except Exception as e:
        logger.warning("Failed to save history CSV (non-fatal): %s", e)

    # Re-fetch recent Google Play data to correct retroactive GCS updates
    try:
        recent_gp = google_client.fetch_recent_reports(target_date=yesterday)
        if recent_gp:
            corrected = correct_history_rows(recent_gp)
            if corrected:
                for key, total in corrected.items():
                    cumulative[key] = total
                save_cumulative_totals(cumulative)
                logger.info("Applied Google Play retroactive corrections")
    except Exception as e:
        logger.warning("Google Play correction check failed (non-fatal): %s", e)

    # Format and send report
    message = format_report(results, report_time=now)
    logger.info("Report:\n%s", message)

    success = send_telegram_message(config.telegram, message)
    if not success:
        logger.error("Failed to send Telegram message after retries")
        sys.exit(1)

    logger.info("Daily download report sent successfully")


if __name__ == "__main__":
    main()
