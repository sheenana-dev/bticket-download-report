"""Shared download formatting helpers (the message itself: test_combined_report)."""

from src.formatter import fmt_count, stale_flag
from src.stores.base import StoreResult


def test_fmt_count():
    assert fmt_count(9999999) == "9,999,999"
    assert fmt_count(0) == "0"
    assert fmt_count(None) == "N/A"


def test_stale_flag_respects_per_store_thresholds():
    # App Store is T-1 (threshold 3); Google Play has a normal ~5-day lag (threshold 7)
    assert stale_flag(StoreResult("App Store", stale_days=3)) is None
    assert stale_flag(StoreResult("App Store", stale_days=4)) == 4
    assert stale_flag(StoreResult("Google Play", stale_days=7)) is None
    assert stale_flag(StoreResult("Google Play", stale_days=12)) == 12


def test_stale_flag_unknown_lag():
    assert stale_flag(StoreResult("App Store")) is None
