"""Build the Telegram report from the CSV history (single source of truth).

Extracted so both the daily job (``src.main``) and the manual refresh tool
(``scripts.refresh_google_play``) render the report through one code path.
"""

from datetime import datetime
from typing import Optional

from src.formatter import format_report
from src.history import get_latest_per_platform
from src.stores.base import StoreResult

# CSV platform key -> display store name, in the order they appear in the report.
PLATFORM_STORE_MAP = {
    "appstore": "App Store",
    "googleplay": "Google Play",
}

# store name -> (daily uninstalls, cumulative uninstalls)
Churn = dict[str, tuple[Optional[int], Optional[int]]]


def build_report_results(
    now: datetime,
    fallback: Optional[list[StoreResult]] = None,
    churn: Optional[Churn] = None,
) -> list[StoreResult]:
    """Assemble per-store results from the CSV, newest row per platform.

    ``fallback`` supplies API results for a platform missing from the CSV
    (e.g. a first-ever run before any row is written). ``churn`` attaches
    uninstall counts (daily, cumulative) per store name when available.
    """
    csv_data = get_latest_per_platform()
    fallback = fallback or []
    churn = churn or {}
    results: list[StoreResult] = []

    for platform_key, store_name in PLATFORM_STORE_MAP.items():
        if platform_key in csv_data:
            d = csv_data[platform_key]
            stale_days = None
            try:
                rd = datetime.strptime(d["report_date"], "%Y-%m-%d")
                data_date_str = rd.strftime("%b %d")
                stale_days = (now.date() - rd.date()).days
            except ValueError:
                data_date_str = d["report_date"]
            results.append(StoreResult(
                store_name=store_name,
                daily_downloads=d["daily_downloads"],
                total_downloads=d["cumulative_total"],
                data_date=data_date_str,
                stale_days=stale_days,
            ))
        else:
            for r in fallback:
                if r.store_name == store_name:
                    results.append(r)
                    break

    for r in results:
        daily_un, total_un = churn.get(r.store_name, (None, None))
        r.daily_uninstalls = daily_un
        r.total_uninstalls = total_un

    return results


def build_report(
    now: datetime,
    fallback: Optional[list[StoreResult]] = None,
    churn: Optional[Churn] = None,
) -> str:
    """Render the full bilingual report string from CSV history."""
    return format_report(build_report_results(now, fallback, churn), report_time=now)
