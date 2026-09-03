"""Google Play revenue from the Play Console GCS exports.

Daily estimate:  gs://<bucket>/sales/salesreport_YYYYMM.zip
    One row per order line. Columns used: Order Charged Date, Financial Status,
    Package ID/Name, Currency of Sale, Charged Amount, Taxes Collected.
    Net is *estimated* as (Charged − Tax) × (1 − fee_rate).

Monthly reconciled:  gs://<bucket>/earnings/earnings_YYYYMM_<account>.zip
    Ledger lines in merchant currency: Transaction Type ∈ {Charge, Google fee,
    Tax, Charge refund, Google fee refund, Tax refund}. Summing every line's
    "Amount (Merchant Currency)" gives what Google actually pays out. Published
    ~5th of the following month.

Both exports are monthly CSV files inside a zip; encoding is UTF-8 or UTF-16
depending on report vintage, so we sniff the BOM.
"""

import csv
import io
import logging
import zipfile
from calendar import monthrange
from datetime import date
from typing import Optional

from google.cloud import storage

from src.config import GooglePlayConfig, RevenueConfig
from src.revenue.fx import FxConverter
from src.revenue.models import BaseRevenueClient, RevenueResult

logger = logging.getLogger(__name__)


def _decode(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def _unzip_csv(blob_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob_bytes)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ValueError("zip contains no CSV")
        return _decode(zf.read(names[0]))


def _col(row: dict, *candidates: str) -> str:
    """First matching column by exact name, then by case-insensitive substring."""
    for c in candidates:
        if c in row:
            return (row[c] or "").strip()
    lowered = {k.lower(): k for k in row}
    for c in candidates:
        for lk, k in lowered.items():
            if c.lower() in lk:
                return (row[k] or "").strip()
    return ""


def _money(value: str) -> float:
    try:
        return float(value.replace(",", "") or 0)
    except ValueError:
        return 0.0


class GooglePlayRevenueClient(BaseRevenueClient):
    store_name = "Google Play"

    def __init__(self, config: GooglePlayConfig, revenue: RevenueConfig, fx: FxConverter,
                 client: Optional[storage.Client] = None):
        self.config = config
        self.revenue = revenue
        self.fx = fx
        self.client = client or storage.Client()
        self._blob_cache: dict[str, Optional[bytes]] = {}

    # -- GCS -------------------------------------------------------------
    def _download(self, blob_path: str) -> Optional[bytes]:
        if blob_path in self._blob_cache:
            return self._blob_cache[blob_path]
        try:
            data = self.client.bucket(self.config.bucket_id).blob(blob_path).download_as_bytes()
        except Exception as e:  # noqa: BLE001 — missing month is normal early in the month
            logger.warning("Could not download gs://%s/%s: %s", self.config.bucket_id, blob_path, e)
            data = None
        self._blob_cache[blob_path] = data
        return data

    def _find_earnings_blob(self, year_month: str) -> Optional[str]:
        prefix = f"earnings/earnings_{year_month}"
        try:
            blobs = list(self.client.list_blobs(self.config.bucket_id, prefix=prefix))
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not list earnings blobs %s: %s", prefix, e)
            return None
        zips = sorted(b.name for b in blobs if b.name.endswith(".zip"))
        return zips[-1] if zips else None

    def _is_ours(self, row: dict) -> bool:
        pkg = _col(row, "Package ID", "Package Name", "Package")
        return (not pkg) or pkg == self.config.package_name

    # -- daily estimate --------------------------------------------------
    def parse_sales_csv(self, text: str, target_date: date) -> RevenueResult:
        reader = csv.DictReader(io.StringIO(text))
        target = target_date.isoformat()
        gross = tax = 0.0
        txns = refunds = trials = 0
        native: dict = {}

        for row in reader:
            charged_date = _col(row, "Order Charged Date")
            if charged_date != target or not self._is_ours(row):
                continue
            status = _col(row, "Financial Status").lower()
            ccy = _col(row, "Currency of Sale") or "PHP"
            amount = _money(_col(row, "Charged Amount"))
            tax_amt = _money(_col(row, "Taxes Collected"))
            if status == "charged" and amount == 0:
                trials += 1              # free-trial start: order exists, nothing charged
                continue
            if status == "charged":
                txns += 1
                sign = 1.0
            elif status in ("refund", "refunded", "charged back", "chargeback"):
                refunds += 1
                sign = -1.0
            else:
                continue  # Pending / Cancelled — not money
            gross += sign * self.fx.convert(amount, ccy, target_date)
            tax += sign * self.fx.convert(tax_amt, ccy, target_date)
            native[ccy] = native.get(ccy, 0.0) + sign * amount

        net = (gross - tax) * (1.0 - self.revenue.google_fee_rate)
        return RevenueResult(
            store_name=self.store_name,
            period_start=target_date,
            period_end=target_date,
            gross=round(gross, 2),
            net=round(net, 2),
            transactions=txns,
            refunds=refunds,
            trials=trials,
            basis="estimate",
            native_gross={k: round(v, 2) for k, v in native.items()},
            note=f"net est. at {self.revenue.google_fee_rate:.0%} fee",
        )

    def fetch_daily(self, target_date: date) -> RevenueResult:
        ym = target_date.strftime("%Y%m")
        try:
            raw = self._download(f"sales/salesreport_{ym}.zip")
            if raw is None:
                return RevenueResult(self.store_name, target_date, target_date,
                                     note=f"no Play sales export for {ym} yet")
            return self.parse_sales_csv(_unzip_csv(raw), target_date)
        except Exception as e:  # noqa: BLE001
            logger.error("Google Play revenue fetch failed: %s", e, exc_info=True)
            return RevenueResult(self.store_name, target_date, target_date, error_message=str(e))

    # -- monthly reconciled ----------------------------------------------
    def parse_earnings_csv(self, text: str, year: int, month: int) -> RevenueResult:
        reader = csv.DictReader(io.StringIO(text))
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        gross = fees = tax = net = 0.0
        txns = refunds = 0
        native: dict = {}
        merchant_ccy = None

        for row in reader:
            if not self._is_ours(row):
                continue
            ttype = _col(row, "Transaction Type").lower()
            merchant_ccy = _col(row, "Merchant Currency") or merchant_ccy or "PHP"
            amt = _money(_col(row, "Amount (Merchant Currency)"))
            amt_report = self.fx.convert(amt, merchant_ccy, date(year, month, 15))
            net += amt_report
            if ttype == "charge":
                gross += amt_report
                txns += 1
            elif ttype == "charge refund":
                gross += amt_report
                refunds += 1
            elif "fee" in ttype:
                fees += amt_report
            elif "tax" in ttype:
                tax += amt_report
            native[merchant_ccy] = native.get(merchant_ccy, 0.0) + (amt if "charge" in ttype and "fee" not in ttype else 0.0)

        return RevenueResult(
            store_name=self.store_name,
            period_start=start,
            period_end=end,
            gross=round(gross, 2),
            net=round(net, 2),
            transactions=txns,
            refunds=refunds,
            basis="reconciled",
            native_gross={k: round(v, 2) for k, v in native.items()},
            note=f"fees {fees:,.0f} · tax {tax:,.0f} ({merchant_ccy or 'PHP'} ledger)",
        )

    def fetch_month(self, year: int, month: int) -> RevenueResult:
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        ym = f"{year:04d}{month:02d}"
        try:
            blob = self._find_earnings_blob(ym)
            if blob is None:
                return RevenueResult(self.store_name, start, end,
                                     note="Play earnings report not published yet (usually ~5th)")
            raw = self._download(blob)
            if raw is None:
                return RevenueResult(self.store_name, start, end, error_message=f"could not download {blob}")
            return self.parse_earnings_csv(_unzip_csv(raw), year, month)
        except Exception as e:  # noqa: BLE001
            logger.error("Google Play earnings fetch failed: %s", e, exc_info=True)
            return RevenueResult(self.store_name, start, end, error_message=str(e))
