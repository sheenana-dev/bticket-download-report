from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class StoreResult:
    store_name: str
    daily_downloads: Optional[int] = None
    total_downloads: Optional[int] = None
    data_date: Optional[str] = None
    error_message: Optional[str] = None
    # How many days the reported data lags the run date. Used to flag stale
    # sources (e.g. a stalled store export) in the report. None = unknown.
    stale_days: Optional[int] = None
    # Churn: uninstalls for the latest day and cumulative all-time. None when the
    # source can't provide them (e.g. Apple Sales API has no deletion data).
    daily_uninstalls: Optional[int] = None
    total_uninstalls: Optional[int] = None


class BaseStoreClient(ABC):
    @abstractmethod
    def fetch_report(self, target_date: date) -> StoreResult:
        """Fetch daily and total download metrics.

        Must not raise — returns StoreResult with error_message on failure.
        """
