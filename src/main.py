import json
import os
import sys
from datetime import datetime, timedelta
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
from src.telegram import send_telegram_message
from src.utils.logger import setup_logging

CACHE_FILE = "cumulative_totals.json"


def load_cumulative_totals() -> dict:
    """Load cached cumulative totals from file."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {"apple": 0, "google_play": 0}


def save_cumulative_totals(totals: dict):
    """Save updated cumulative totals for next run."""
    with open(CACHE_FILE, "w") as f:
        json.dump(totals, f, indent=2)


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
    logger.info("Fetching Apple App Store data...")
    apple_client = AppleStoreClient(config.apple)
    apple_result = apple_client.fetch_report(target_date=yesterday)
    if apple_result.daily_downloads is not None:
        cumulative["apple"] = cumulative.get("apple", 0) + apple_result.daily_downloads
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
        if google_result.data_date != last_gp_date:
            cumulative["google_play"] = cumulative.get("google_play", 0) + google_result.daily_downloads
            cumulative["google_play_last_date"] = google_result.data_date
    gp_total = cumulative.get("google_play", 0)
    google_result.total_downloads = gp_total if gp_total > 0 else None
    results.append(google_result)

    # Save cumulative totals
    cumulative["last_updated"] = now.isoformat()
    save_cumulative_totals(cumulative)

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
