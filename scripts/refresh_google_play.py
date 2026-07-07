#!/usr/bin/env python3
"""Manually refresh Google Play daily installs from Play Console figures.

Use when the GCS bulk export is frozen (Google-side) but the Play Console UI
still shows current numbers (Statistics -> e.g. "device acquisition").

Examples:
    python scripts/refresh_google_play.py --pairs "2026-06-18:149,2026-06-19:153"
    python scripts/refresh_google_play.py --csv play_export.csv
    python scripts/refresh_google_play.py --csv play_export.csv --column "All countries / regions"

Previews the resulting report (no Telegram send). To deliver it to the group:
    git add data/downloads.csv
    git commit -m "chore: manual Google Play refresh"
    git push
    gh workflow run daily_report.yml    # or wait for the scheduled run
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from datetime import datetime
from zoneinfo import ZoneInfo

from src.manual_refresh import apply_google_refresh, parse_csv, parse_pairs
from src.report import build_report
from src.utils.logger import setup_logging


def _read_csv(path: str) -> str:
    # utf-8-sig strips a BOM if the Play Console export includes one.
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        return f.read()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pairs", help='Comma-separated DATE:COUNT (e.g. "2026-06-18:149,2026-06-19:153")')
    source.add_argument("--csv", help="Path to a Play Console CSV export")
    parser.add_argument("--column", help="CSV value column (default: first non-date, non-percentage column)")
    args = parser.parse_args()

    logger = setup_logging()

    daily = parse_pairs(args.pairs) if args.pairs else parse_csv(_read_csv(args.csv), args.column)
    if not daily:
        logger.error("No valid rows parsed from input.")
        sys.exit(1)

    logger.info("Parsed %d day(s): %s .. %s", len(daily), min(daily), max(daily))
    updated = apply_google_refresh(daily)
    if updated is None:
        logger.info("No changes — the CSV already matches these values.")
    else:
        logger.info("Reconciled. Google Play cumulative is now %d.", updated.get("google_play", -1))

    now = datetime.now(ZoneInfo("Asia/Manila"))
    preview = build_report(now).replace("<pre>", "").replace("</pre>", "")
    print("\n----- REPORT PREVIEW -----\n" + preview + "\n--------------------------")
    print(
        "\nTo deliver: commit data/downloads.csv, push, then "
        "`gh workflow run daily_report.yml` (or wait for the scheduled run)."
    )


if __name__ == "__main__":
    main()
