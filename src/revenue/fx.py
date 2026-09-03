"""FX conversion into the report currency.

Uses the Frankfurter API (ECB reference rates, no key needed) with a per-run
in-memory cache and a per-day on-disk cache in ``data/fx_cache.json`` so
GitHub Actions runs are reproducible and re-runs don't re-hit the API.
Overrides from ``REVENUE_FX_OVERRIDES`` always win (use them for currencies
the ECB doesn't publish, or to pin a treasury rate).
"""

import json
import logging
import os
from datetime import date, timedelta
from typing import Optional

import requests

from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

FX_API = "https://api.frankfurter.app/{day}"
CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "fx_cache.json"
)


class FxConverter:
    def __init__(self, report_currency: str = "PHP", overrides: Optional[dict] = None,
                 cache_path: str = CACHE_PATH):
        self.report_currency = report_currency.upper()
        self.overrides = {k.upper(): float(v) for k, v in (overrides or {}).items()}
        self.cache_path = cache_path
        self._cache: dict = self._load_cache()

    # -- cache -----------------------------------------------------------
    def _load_cache(self) -> dict:
        try:
            with open(self.cache_path) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w") as fh:
                json.dump(self._cache, fh, indent=2, sort_keys=True)
        except OSError as e:
            logger.warning("Could not persist FX cache: %s", e)

    # -- fetch -----------------------------------------------------------
    @with_retry(max_retries=2, base_delay=1.0, exceptions=(requests.RequestException,))
    def _fetch_day(self, day: date) -> dict:
        """Rates for `day` quoted as 1 unit of each currency -> report currency."""
        # Frankfurter returns base EUR: {"rates": {"PHP": 61.2, "USD": 1.08}}
        # for 1 EUR. We derive X->report for every X from that single table.
        resp = requests.get(FX_API.format(day=day.isoformat()), timeout=20)
        resp.raise_for_status()
        table = resp.json()
        eur_to_report = table["rates"].get(self.report_currency)
        if eur_to_report is None and self.report_currency != "EUR":
            raise ValueError(f"FX provider has no rate for {self.report_currency}")
        if self.report_currency == "EUR":
            eur_to_report = 1.0
        rates = {"EUR": eur_to_report}
        for code, eur_to_code in table["rates"].items():
            if eur_to_code:
                rates[code] = eur_to_report / eur_to_code
        rates[self.report_currency] = 1.0
        rates["_as_of"] = table.get("date", day.isoformat())
        return rates

    def rates_for(self, day: date) -> dict:
        key = f"{day.isoformat()}:{self.report_currency}"
        if key not in self._cache:
            # Weekends/holidays: Frankfurter serves the last business day, which
            # is exactly what we want.
            self._cache[key] = self._fetch_day(day)
            self._save_cache()
        return self._cache[key]

    # -- convert ---------------------------------------------------------
    def rate(self, currency: str, day: date) -> float:
        code = currency.upper()
        if code == self.report_currency:
            return 1.0
        if code in self.overrides:
            return self.overrides[code]
        rates = self.rates_for(day)
        if code not in rates:
            raise KeyError(f"No FX rate for {code} on {day}; set REVENUE_FX_OVERRIDES={code}:<rate>")
        return float(rates[code])

    def convert(self, amount: float, currency: str, day: date) -> float:
        return amount * self.rate(currency, day)

    def month_rate(self, currency: str, year: int, month: int) -> float:
        """Mid-month rate: cheap, stable proxy for a monthly average."""
        return self.rate(currency, date(year, month, 15))


class StaticFx(FxConverter):
    """Test/offline converter: fixed table, no network."""

    def __init__(self, table: dict, report_currency: str = "PHP"):
        super().__init__(report_currency=report_currency, overrides=table, cache_path=os.devnull)

    def _load_cache(self) -> dict:  # pragma: no cover
        return {}

    def _save_cache(self) -> None:  # pragma: no cover
        return None

    def rates_for(self, day: date) -> dict:  # pragma: no cover
        return dict(self.overrides)
