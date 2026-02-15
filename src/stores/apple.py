import csv
import gzip
import io
import logging
import time
from datetime import date, timedelta

import jwt
import requests

from src.config import AppleConfig
from src.stores.base import BaseStoreClient, StoreResult
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

API_BASE = "https://api.appstoreconnect.apple.com"
# Product types that represent new downloads (not updates)
# 1 = iPhone/Universal (paid), 1F = iPhone/Universal (free)
# Excluded: 3/3F (iPad-only), 1-B (B2B/Volume Purchase), 7/7F/7T (updates)
DOWNLOAD_PRODUCT_TYPES = {"1", "1F"}


class AppleStoreClient(BaseStoreClient):
    def __init__(self, config: AppleConfig):
        self.config = config

    def _generate_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iss": self.config.issuer_id,
            "iat": now,
            "exp": now + 600,
            "aud": "appstoreconnect-v1",
        }
        headers = {
            "alg": "ES256",
            "kid": self.config.key_id,
            "typ": "JWT",
        }
        return jwt.encode(payload, self.config.private_key, algorithm="ES256", headers=headers)

    @with_retry(max_retries=2, base_delay=2.0, exceptions=(requests.ConnectionError, requests.Timeout))
    def _fetch_sales_report(self, target_date: date) -> bytes:
        token = self._generate_jwt()
        resp = requests.get(
            f"{API_BASE}/v1/salesReports",
            params={
                "filter[reportType]": "SALES",
                "filter[reportSubType]": "SUMMARY",
                "filter[frequency]": "DAILY",
                "filter[reportDate]": target_date.strftime("%Y-%m-%d"),
                "filter[vendorNumber]": self.config.vendor_number,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if resp.status_code >= 500:
            raise requests.ConnectionError(f"Server error: {resp.status_code}")
        resp.raise_for_status()
        return resp.content

    def _parse_tsv(self, gzipped_data: bytes) -> int:
        raw = gzip.decompress(gzipped_data)
        text = raw.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")

        total_units = 0
        for row in reader:
            sku = row.get("SKU", "").strip()
            product_type = row.get("Product Type Identifier", "").strip()
            units = row.get("Units", "0").strip()
            title = row.get("Title", "").strip()

            if sku == self.config.app_sku:
                logger.info(
                    "Apple TSV row — SKU: %s, Title: %s, Product Type: %s, Units: %s",
                    sku, title, product_type, units,
                )
                if product_type in DOWNLOAD_PRODUCT_TYPES:
                    try:
                        total_units += int(units)
                    except (ValueError, TypeError):
                        pass
                else:
                    logger.info("  -> Skipped (product type '%s' not in download types)", product_type)

        logger.info("Apple total download units for SKU %s: %d", self.config.app_sku, total_units)
        return total_units

    def fetch_report(self, target_date: date) -> StoreResult:
        # Try target_date first, then fall back up to 2 days earlier
        for days_back in range(3):
            check_date = target_date - timedelta(days=days_back)
            try:
                data = self._fetch_sales_report(check_date)
                daily = self._parse_tsv(data)
                return StoreResult(
                    store_name="App Store",
                    daily_downloads=daily,
                    data_date=check_date.strftime("%b %d"),
                )
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    logger.info("Apple report not available for %s, trying earlier date", check_date)
                    continue
                logger.error("Apple App Store fetch failed: %s", e, exc_info=True)
                return StoreResult(store_name="App Store", error_message=str(e))
            except Exception as e:
                logger.error("Apple App Store fetch failed: %s", e, exc_info=True)
                return StoreResult(store_name="App Store", error_message=str(e))

        return StoreResult(
            store_name="App Store",
            data_date=f"{target_date.strftime('%b %d')} (delayed)",
        )
