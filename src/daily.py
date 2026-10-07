"""Combined daily report: downloads + net revenue in ONE Telegram message.

    python -m src.daily [--dry-run]

Each half is collected independently: if one fails, its section reads
"unavailable" and the other still goes out. The run still exits non-zero
afterwards so the GitHub Actions run shows red and the failure gets noticed.

The standalone entry points (`python -m src.main`, `python -m src.revenue.main
daily`) still work for debugging a single half.
"""

import argparse
import logging
import sys
from datetime import datetime
from typing import Callable, Optional, TypeVar
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.combined_report import format_combined
from src.config import load_config
from src.main import collect_downloads
from src.revenue.main import collect_daily
from src.telegram import send_telegram_message
from src.utils.logger import setup_logging

logger = logging.getLogger("daily_report")
T = TypeVar("T")


def _safe(label: str, collect: Callable[[], T]) -> Optional[T]:
    """Run one section's collection; None (rendered as unavailable) on failure."""
    try:
        return collect()
    except Exception:  # noqa: BLE001 — one half must never take down the other
        logger.exception("%s collection failed — section will show as unavailable", label)
        return None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Combined B-Ticket daily report")
    parser.add_argument("--dry-run", action="store_true", help="Build and log, don't send")
    args = parser.parse_args(argv)

    setup_logging()
    try:
        config = load_config()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        return 1

    now = datetime.now(ZoneInfo(config.timezone))
    downloads = _safe("Downloads", lambda: collect_downloads(config, now))
    revenue = _safe("Revenue", lambda: collect_daily(config, now))

    message = format_combined(downloads, revenue, now)
    logger.info("Report:\n%s", message)

    if downloads is None and revenue is None:
        logger.error("Both sections failed — not sending an empty report")
        return 1
    if args.dry_run:
        logger.info("Dry run — skipping Telegram send")
        return 0
    if not send_telegram_message(config.telegram, message):
        logger.error("Failed to send Telegram message after retries")
        return 1

    logger.info("Combined daily report sent successfully")
    return 0 if downloads is not None and revenue is not None else 1


if __name__ == "__main__":
    sys.exit(main())
