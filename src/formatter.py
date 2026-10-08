"""Shared formatting helpers for download figures.

The message itself is rendered by src.combined_report (one combined daily
message); the old standalone bilingual download report was removed.
"""

from typing import Optional

from src.stores.base import StoreResult

# Flag a store as stale when its latest data lags the run date by more than N
# days. App Store is T-1; Google Play carries an inherent ~5-day export delay,
# so its threshold is higher to avoid false alarms on normal lag.
STALE_THRESHOLDS = {"App Store": 3, "Google Play": 7}
DEFAULT_STALE_THRESHOLD = 5


def fmt_count(value: Optional[int]) -> str:
    """Format a number with commas, or 'N/A' if None."""
    if value is None:
        return "N/A"
    return f"{value:,}"


def stale_flag(r: StoreResult) -> Optional[int]:
    """Return how many days the store's data is stale, or None if within range."""
    if r.stale_days is None:
        return None
    threshold = STALE_THRESHOLDS.get(r.store_name, DEFAULT_STALE_THRESHOLD)
    return r.stale_days if r.stale_days > threshold else None
