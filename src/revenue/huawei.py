"""Huawei AppGallery in-app payment revenue via the AGC Reports API.

Same auth as the download client (client-credentials token, `client_id`
header). The IAP/payment export follows the same shape as appDownloadExport:
GET <path>/{appId}?language=en-US&startTime=YYYYMMDD&endTime=YYYYMMDD
→ {"ret": {"code": 0}, "fileURL": "..."} → CSV.

Huawei's report docs differ by region and the column names are localised, so
the path and amount/count column names are configurable
(HUAWEI_IAP_REPORT_PATH / HUAWEI_IAP_AMOUNT_COLUMN / HUAWEI_IAP_COUNT_COLUMN).
Run `python -m src.revenue.main probe huawei` to print the raw headers once
and pin them.
"""

import csv
import io
import logging
from calendar import monthrange
from datetime import date
from typing import Optional

import requests

from src.config import HuaweiConfig, RevenueConfig
from src.revenue.fx import FxConverter
from src.revenue.models import BaseRevenueClient, RevenueResult
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

API_BASE = "https://connect-api.cloud.huawei.com"
TOKEN_URL = f"{API_BASE}/api/oauth2/v1/token"


class HuaweiRevenueClient(BaseRevenueClient):
    store_name = "Huawei"

    def __init__(self, config: HuaweiConfig, revenue: RevenueConfig, fx: FxConverter):
        self.config = config
        self.revenue = revenue
        self.fx = fx
        self._token: Optional[str] = None

    @with_retry(max_retries=2, base_delay=2.0, exceptions=(requests.RequestException,))
    def _get_token(self) -> str:
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
        token = resp.json().get("access_token")
        if not token:
            raise ValueError("No access_token in Huawei response")
        return token

    @with_retry(max_retries=2, base_delay=2.0, exceptions=(requests.RequestException,))
    def fetch_csv(self, start: date, end: date) -> str:
        """Raw CSV text for [start, end]. Empty string when Huawei has no file."""
        if self._token is None:
            self._token = self._get_token()
        url = API_BASE + self.revenue.huawei_iap_report_path.format(app_id=self.config.app_id)
        resp = requests.get(
            url,
            params={
                "language": "en-US",
                "startTime": start.strftime("%Y%m%d"),
                "endTime": end.strftime("%Y%m%d"),
                "groupBy": "date",
                "timeType": "day",
                "currency": self.revenue.huawei_currency,
                "exportType": "CSV",
            },
            headers={
                "Authorization": f"Bearer {self._token}",
                "client_id": self.config.client_id,
                # Team/developer ID. Without it the report service answers 403
                # "client token authorization fail" regardless of client role.
                "uid": self.revenue.huawei_uid,
            },
            timeout=30,
        )
        if resp.status_code >= 500:
            raise requests.RequestException(f"Server error: {resp.status_code}")
        if 400 <= resp.status_code < 500:
            # Not retryable — surface immediately instead of 3x backoff.
            raise ValueError(f"Huawei {resp.status_code}: {resp.text[:200]} (check HUAWEI_UID / client / app id)")
        data = resp.json()
        if data.get("ret", {}).get("code") != 0:
            raise ValueError(f"Huawei API error: {data.get('ret')}")
        file_url = data.get("fileURL")
        if not file_url:
            return ""
        csv_resp = requests.get(file_url, timeout=30)
        csv_resp.raise_for_status()
        return csv_resp.content.decode("utf-8-sig")

    @staticmethod
    def _num(value: Optional[str]) -> float:
        try:
            return float((value or "0").strip().replace(",", "") or 0)
        except ValueError:
            return 0.0

    def _find_col(self, row: dict, wanted: str) -> Optional[str]:
        if wanted in row:
            return wanted
        w = wanted.lower()
        for k in row:
            if w in k.lower():
                return k
        return None

    def _zero(self, start: date, end: date) -> RevenueResult:
        """A successful export with no rows means no sales — report ₱0, like the other stores."""
        return RevenueResult(
            store_name=self.store_name, period_start=start, period_end=end,
            gross=0.0, net=0.0, transactions=0, refunds=0, basis="estimate",
            native_gross={}, note="no sales",
        )

    def parse_csv(self, text: str, start: date, end: date, fx_day: date) -> RevenueResult:
        if not text.strip():
            return self._zero(start, end)
        reader = csv.DictReader(io.StringIO(text))
        gross_native = 0.0
        count = 0
        matched = False
        amount_col = count_col = None
        for row in reader:
            if amount_col is None:
                amount_col = self._find_col(row, self.revenue.huawei_amount_column)
                count_col = self._find_col(row, self.revenue.huawei_count_column)
                if amount_col is None:
                    return RevenueResult(
                        self.store_name, start, end,
                        error_message=(
                            f"Huawei CSV has no '{self.revenue.huawei_amount_column}' column; "
                            f"columns={list(row.keys())}. Set HUAWEI_IAP_AMOUNT_COLUMN."
                        ),
                    )
            row_date = (row.get("Date") or row.get("date") or "").strip().replace("-", "")
            if row_date and not (start.strftime("%Y%m%d") <= row_date <= end.strftime("%Y%m%d")):
                continue
            matched = True
            gross_native += self._num(row.get(amount_col))
            if count_col:
                count += int(self._num(row.get(count_col)))

        if not matched:
            return self._zero(start, end)

        ccy = self.revenue.huawei_currency
        gross = self.fx.convert(gross_native, ccy, fx_day)
        net = gross * (1.0 - self.revenue.huawei_fee_rate)
        return RevenueResult(
            store_name=self.store_name,
            period_start=start,
            period_end=end,
            gross=round(gross, 2),
            net=round(net, 2),
            transactions=count or None,
            basis="estimate",
            native_gross={ccy: round(gross_native, 2)},
            note=f"net est. at {self.revenue.huawei_fee_rate:.0%} fee",
        )

    def fetch_daily(self, target_date: date) -> RevenueResult:
        try:
            text = self.fetch_csv(target_date, target_date)
            return self.parse_csv(text, target_date, target_date, target_date)
        except Exception as e:  # noqa: BLE001
            logger.error("Huawei revenue fetch failed: %s", e, exc_info=True)
            return RevenueResult(self.store_name, target_date, target_date, error_message=str(e))

    def fetch_month(self, year: int, month: int) -> RevenueResult:
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        try:
            text = self.fetch_csv(start, end)
            result = self.parse_csv(text, start, end, date(year, month, 15))
            # Huawei has no ledger export we can reach; the month is still an
            # estimate (fee by rate), flagged as such in the PDF.
            result.basis = "estimate"
            return result
        except Exception as e:  # noqa: BLE001
            logger.error("Huawei monthly revenue fetch failed: %s", e, exc_info=True)
            return RevenueResult(self.store_name, start, end, error_message=str(e))
