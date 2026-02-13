import csv
import io
import logging
from datetime import date
from typing import Optional

import requests

from src.config import HuaweiConfig
from src.stores.base import BaseStoreClient, StoreResult
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

TOKEN_URL = "https://connect-api.cloud.huawei.com/api/oauth2/v1/token"
REPORT_URL = (
    "https://connect-api.cloud.huawei.com/api/report/distribution-operation-quality"
    "/v1/appDownloadExport/{app_id}"
)


class HuaweiClient(BaseStoreClient):
    def __init__(self, config: HuaweiConfig):
        self.config = config
        self._access_token: Optional[str] = None

    @with_retry(max_retries=2, base_delay=2.0, exceptions=(requests.RequestException,))
    def _get_access_token(self) -> str:
        resp = requests.post(
            TOKEN_URL,
            json={
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise ValueError(f"No access_token in Huawei response: {data}")
        return token

    @with_retry(max_retries=2, base_delay=2.0, exceptions=(requests.RequestException,))
    def _fetch_report_csv(self, target_date: date) -> str:
        """Fetch the download report CSV for a single date."""
        if self._access_token is None:
            self._access_token = self._get_access_token()

        date_str = target_date.strftime("%Y%m%d")
        url = REPORT_URL.format(app_id=self.config.app_id)

        resp = requests.get(
            url,
            params={
                "language": "en-US",
                "startTime": date_str,
                "endTime": date_str,
            },
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "client_id": self.config.client_id,
            },
            timeout=30,
        )

        if resp.status_code >= 500:
            raise requests.RequestException(f"Server error: {resp.status_code}")
        resp.raise_for_status()

        data = resp.json()
        if data.get("ret", {}).get("code") != 0:
            raise ValueError(f"Huawei API error: {data.get('ret', {})}")

        file_url = data.get("fileURL")
        if not file_url:
            return ""

        csv_resp = requests.get(file_url, timeout=30)
        csv_resp.raise_for_status()
        # Decode as UTF-8 with BOM handling (Huawei CSV uses UTF-8 BOM)
        return csv_resp.content.decode("utf-8-sig")

    def _parse_csv(self, csv_text: str, target_date: date) -> Optional[int]:
        """Parse Huawei CSV for daily new downloads on target date."""
        if not csv_text.strip():
            return None

        reader = csv.DictReader(io.StringIO(csv_text))

        target_str = target_date.strftime("%Y%m%d")

        for row in reader:
            row_date = row.get("Date", "").strip()
            if row_date == target_str:
                try:
                    return int(row.get("New downloads", 0))
                except (ValueError, TypeError):
                    return 0

        return None

    def fetch_report(self, target_date: date) -> StoreResult:
        try:
            csv_text = self._fetch_report_csv(target_date)
            daily = self._parse_csv(csv_text, target_date)

            if daily is not None:
                return StoreResult(
                    store_name="Huawei",
                    daily_downloads=daily,
                    data_date=target_date.strftime("%b %d"),
                )

            logger.warning("No Huawei download data for %s", target_date)
            return StoreResult(
                store_name="Huawei",
                data_date=f"{target_date.strftime('%b %d')} (delayed)",
            )

        except Exception as e:
            logger.error("Huawei AppGallery fetch failed: %s", e, exc_info=True)
            return StoreResult(
                store_name="Huawei",
                error_message=str(e),
            )
