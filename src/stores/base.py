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


class BaseStoreClient(ABC):
    @abstractmethod
    def fetch_report(self, target_date: date) -> StoreResult:
        """Fetch daily and total download metrics.

        Must not raise — returns StoreResult with error_message on failure.
        """
