import csv
import io
import logging
from datetime import date, timedelta
from typing import Optional

from google.cloud import storage
from google.oauth2 import service_account

from src.config import GooglePlayConfig
from src.stores.base import BaseStoreClient, StoreResult

logger = logging.getLogger(__name__)

# bucket_id in config is the full bucket name (e.g. pubsite_prod_7245262499315294571)


class GooglePlayClient(BaseStoreClient):
    def __init__(self, config: GooglePlayConfig):
        self.config = config
        self.client = storage.Client()

    def _get_blob_path(self, year_month: str) -> str:
        return (
            f"stats/installs/installs_{self.config.package_name}"
            f"_{year_month}_overview.csv"
        )

    def _download_csv(self, year_month: str) -> Optional[str]:
        bucket_name = self.config.bucket_id
        blob_path = self._get_blob_path(year_month)

        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            return blob.download_as_text(encoding="utf-16")
        except Exception as e:
            logger.warning("Could not download GCS blob %s/%s: %s", bucket_name, blob_path, e)
            return None

    def _parse_csv(self, csv_text: str, target_date: date) -> Optional[int]:
        """Parse Google Play installs CSV. Returns daily user installs."""
        reader = csv.DictReader(io.StringIO(csv_text))

        target_str = target_date.strftime("%Y-%m-%d")

        for row in reader:
            row_date = row.get("Date", "").strip()
            if row_date == target_str:
                daily_user = self._safe_int(row.get("Daily User Installs"))
                daily_device = self._safe_int(row.get("Daily Device Installs"))
                total_user = self._safe_int(row.get("Total User Installs"))
                logger.info(
                    "Google Play CSV row — Date: %s, Daily User Installs: %s, "
                    "Daily Device Installs: %s, Total User Installs: %s",
                    row_date, daily_user, daily_device, total_user,
                )
                return daily_user

        return None

    @staticmethod
    def _safe_int(value: Optional[str]) -> Optional[int]:
        if value is None:
            return None
        value = value.strip().replace(",", "")
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def fetch_recent_reports(self, target_date: date, lookback_days: int = 7) -> list[StoreResult]:
        """Re-fetch daily data for the last N days to detect retroactive corrections."""
        results = []
        csv_cache: dict[str, Optional[str]] = {}

        for days_offset in range(lookback_days):
            check_date = target_date - timedelta(days=days_offset)
            year_month = check_date.strftime("%Y%m")

            if year_month not in csv_cache:
                csv_cache[year_month] = self._download_csv(year_month)

            csv_text = csv_cache[year_month]
            if csv_text is None:
                continue

            daily = self._parse_csv(csv_text, check_date)
            if daily is not None:
                results.append(StoreResult(
                    store_name="Google Play",
                    daily_downloads=daily,
                    data_date=check_date.strftime("%b %d"),
                ))

        return results

    def fetch_report(self, target_date: date) -> StoreResult:
        try:
            # Google Play CSV data has ~5 day delay, try up to 7 days back
            for days_offset in range(7):
                check_date = target_date - timedelta(days=days_offset)
                year_month = check_date.strftime("%Y%m")
                csv_text = self._download_csv(year_month)

                if csv_text is None:
                    continue

                daily = self._parse_csv(csv_text, check_date)
                if daily is not None:
                    return StoreResult(
                        store_name="Google Play",
                        daily_downloads=daily,
                        data_date=check_date.strftime("%b %d"),
                    )

            logger.warning("No Google Play data found for %s or preceding days", target_date)
            return StoreResult(
                store_name="Google Play",
                data_date=f"{target_date.strftime('%b %d')} (delayed)",
            )

        except Exception as e:
            logger.error("Google Play fetch failed: %s", e, exc_info=True)
            return StoreResult(
                store_name="Google Play",
                error_message=str(e),
            )
