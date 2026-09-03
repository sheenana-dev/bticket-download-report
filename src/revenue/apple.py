"""Apple App Store revenue via the Sales Reports API.

Daily:   GET /v1/salesReports  reportType=SALES subType=SUMMARY frequency=DAILY
Monthly: same endpoint with frequency=MONTHLY (reportDate=YYYY-MM) — Apple's
own monthly roll-up, so it reconciles with Sales & Trends. FINANCIAL reports
(fiscal-calendar, per region) are the payout truth but need per-region calls;
the monthly SALES proceeds are what finance normally ties to first.

Money columns in the TSV:
  Units                 signed; refunds are negative rows
  Customer Price        per-unit price the customer paid, in `Customer Currency`
  Developer Proceeds    per-unit amount Apple pays us, in `Currency of Proceeds`
                        (already net of Apple's commission, before any
                        withholding tax)

We only count rows whose Parent Identifier (or SKU) is our app and whose
Product Type Identifier is an in-app purchase / subscription type.
"""

import csv
import gzip
import io
import logging
import time
from calendar import monthrange
from datetime import date, timedelta

import jwt
import requests

from src.config import AppleConfig
from src.revenue.fx import FxConverter
from src.revenue.models import BaseRevenueClient, RevenueResult
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

API_BASE = "https://api.appstoreconnect.apple.com"

# In-app product types (Apple "Product Type Identifiers" reference):
#   IA1 / IA1-M  in-app purchase (consumable, non-consumable)
#   IA3          restored non-consumable (zero revenue, kept for counts)
#   IA9 / IA9-M  non-renewing subscription
#   IAY / IAY-M  auto-renewable subscription
#   FI1          Mac in-app purchase
IAP_PRODUCT_TYPES = {"IA1", "IA1-M", "IA3", "IA9", "IA9-M", "IAY", "IAY-M", "FI1"}
SUBSCRIPTION_TYPES = {"IA9", "IA9-M", "IAY", "IAY-M"}


class AppleRevenueClient(BaseRevenueClient):
    store_name = "App Store"

    def __init__(self, config: AppleConfig, fx: FxConverter):
        self.config = config
        self.fx = fx

    def _generate_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iss": self.config.issuer_id,
            "iat": now,
            "exp": now + 600,
            "aud": "appstoreconnect-v1",
        }
        headers = {"alg": "ES256", "kid": self.config.key_id, "typ": "JWT"}
        return jwt.encode(payload, self.config.private_key, algorithm="ES256", headers=headers)

    @with_retry(max_retries=2, base_delay=2.0, exceptions=(requests.ConnectionError, requests.Timeout))
    def _fetch(self, frequency: str, report_date: str) -> bytes:
        resp = requests.get(
            f"{API_BASE}/v1/salesReports",
            params={
                "filter[reportType]": "SALES",
                "filter[reportSubType]": "SUMMARY",
                "filter[frequency]": frequency,
                "filter[reportDate]": report_date,
                "filter[vendorNumber]": self.config.vendor_number,
            },
            headers={"Authorization": f"Bearer {self._generate_jwt()}"},
            timeout=30,
        )
        if resp.status_code >= 500:
            raise requests.ConnectionError(f"Server error: {resp.status_code}")
        resp.raise_for_status()
        return resp.content

    @staticmethod
    def _to_float(value: str) -> float:
        try:
            return float((value or "0").strip().replace(",", ""))
        except ValueError:
            return 0.0

    def _is_ours(self, row: dict) -> bool:
        sku = (row.get("SKU") or "").strip()
        parent = (row.get("Parent Identifier") or "").strip()
        return self.config.app_sku in (sku, parent)

    def parse_tsv(self, gzipped: bytes, fx_day: date) -> RevenueResult:
        """Aggregate IAP/subscription rows into a RevenueResult (period set by caller)."""
        text = gzip.decompress(gzipped).decode("utf-8")
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")

        gross = 0.0
        net = 0.0
        txns = 0
        refunds = 0
        native: dict = {}

        for row in reader:
            ptype = (row.get("Product Type Identifier") or "").strip()
            if ptype not in IAP_PRODUCT_TYPES or not self._is_ours(row):
                continue
            units = int(self._to_float(row.get("Units", "0")))
            cust_price = self._to_float(row.get("Customer Price", "0"))
            proceeds = self._to_float(row.get("Developer Proceeds", "0"))
            cust_ccy = (row.get("Customer Currency") or "USD").strip().upper()
            proc_ccy = (row.get("Currency of Proceeds") or cust_ccy).strip().upper()

            row_gross_native = cust_price * units
            row_net_native = proceeds * units
            gross += self.fx.convert(row_gross_native, cust_ccy, fx_day)
            net += self.fx.convert(row_net_native, proc_ccy, fx_day)
            native[cust_ccy] = native.get(cust_ccy, 0.0) + row_gross_native

            if units > 0:
                txns += units
            elif units < 0:
                refunds += -units

            logger.info(
                "Apple row — %s %s units=%d price=%.2f %s proceeds=%.2f %s",
                row.get("SKU", "").strip(), ptype, units, cust_price, cust_ccy, proceeds, proc_ccy,
            )

        return RevenueResult(
            store_name=self.store_name,
            period_start=fx_day,
            period_end=fx_day,
            gross=round(gross, 2),
            net=round(net, 2),
            transactions=txns,
            refunds=refunds,
            native_gross={k: round(v, 2) for k, v in native.items()},
        )

    def fetch_daily(self, target_date: date) -> RevenueResult:
        # Apple is T-1; on a 404 fall back up to 2 days like the download job.
        for days_back in range(3):
            check = target_date - timedelta(days=days_back)
            try:
                data = self._fetch("DAILY", check.strftime("%Y-%m-%d"))
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    logger.info("Apple sales report not ready for %s", check)
                    continue
                logger.error("Apple revenue fetch failed: %s", e, exc_info=True)
                return RevenueResult(self.store_name, target_date, target_date, error_message=str(e))
            except Exception as e:  # noqa: BLE001 — never raise out of a store client
                logger.error("Apple revenue fetch failed: %s", e, exc_info=True)
                return RevenueResult(self.store_name, target_date, target_date, error_message=str(e))
            result = self.parse_tsv(data, check)
            result.basis = "estimate"
            return result
        return RevenueResult(
            self.store_name, target_date, target_date,
            note=f"no Apple report yet for {target_date:%b %d}",
        )

    def fetch_month(self, year: int, month: int) -> RevenueResult:
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        try:
            data = self._fetch("MONTHLY", f"{year:04d}-{month:02d}")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return RevenueResult(self.store_name, start, end, note="Apple monthly report not published yet")
            return RevenueResult(self.store_name, start, end, error_message=str(e))
        except Exception as e:  # noqa: BLE001
            logger.error("Apple monthly fetch failed: %s", e, exc_info=True)
            return RevenueResult(self.store_name, start, end, error_message=str(e))
        result = self.parse_tsv(data, date(year, month, 15))
        result.period_start, result.period_end = start, end
        result.basis = "reconciled"
        return result
