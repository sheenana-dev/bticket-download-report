from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class RevenueResult:
    """One store's revenue for one period, normalised to the report currency."""

    store_name: str
    period_start: date
    period_end: date
    # Gross = what customers were charged (before store fee, incl. any tax the
    # store collected). Net = what the store owes us. Both in report currency.
    gross: Optional[float] = None
    net: Optional[float] = None
    transactions: Optional[int] = None   # paid units
    refunds: Optional[int] = None
    # Zero-price starts (free trials / intro offers). Leading indicator, not revenue.
    trials: int = 0
    # "estimate" (daily, fee applied by rate) or "reconciled" (store-reported net)
    basis: str = "estimate"
    # Original currencies seen, e.g. {"USD": 12.5, "PHP": 1800.0} (gross, native)
    native_gross: dict = field(default_factory=dict)
    error_message: Optional[str] = None
    # Free-text note surfaced in the report (e.g. "no report yet for date")
    note: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error_message is None and self.gross is not None


class BaseRevenueClient(ABC):
    @abstractmethod
    def fetch_daily(self, target_date: date) -> RevenueResult:
        """Revenue for a single day. Must not raise — set error_message instead."""

    @abstractmethod
    def fetch_month(self, year: int, month: int) -> RevenueResult:
        """Reconciled revenue for a calendar month. Must not raise."""
