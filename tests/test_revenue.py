import csv
import gzip
import io
import os
import zipfile
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest
import responses

from src.config import RevenueConfig
from src.revenue.apple import AppleRevenueClient
from src.revenue.formatter import format_daily, format_monthly_caption
from src.revenue.fx import StaticFx
from src.revenue.google_play import GooglePlayRevenueClient
from src.revenue.history import period_totals, upsert_daily, upsert_monthly, monthly_rows
from src.revenue.huawei import HuaweiRevenueClient
from src.revenue.models import RevenueResult
from src.revenue.pdf import build_monthly_pdf

FX = StaticFx({"USD": 56.0, "JPY": 0.38, "CNY": 7.8, "PHP": 1.0})
REV = RevenueConfig(google_fee_rate=0.15, huawei_fee_rate=0.15)


# ----------------------------------------------------------------------- apple
def _apple_tsv(rows):
    cols = ["Provider", "SKU", "Parent Identifier", "Product Type Identifier", "Units",
            "Developer Proceeds", "Customer Price", "Customer Currency", "Currency of Proceeds", "Title"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, delimiter="\t")
    w.writeheader()
    for r in rows:
        w.writerow({**{c: "" for c in cols}, **r})
    return gzip.compress(buf.getvalue().encode())


def test_apple_counts_only_iap_rows_for_our_app(apple_config):
    tsv = _apple_tsv([
        # free download — not revenue
        {"SKU": "com.bticket.app", "Product Type Identifier": "1F", "Units": "12", "Developer Proceeds": "0", "Customer Price": "0", "Customer Currency": "PHP", "Currency of Proceeds": "PHP"},
        # subscription, 3 units, PHP
        {"SKU": "premium.monthly", "Parent Identifier": "com.bticket.app", "Product Type Identifier": "IAY", "Units": "3", "Developer Proceeds": "127.5", "Customer Price": "150", "Customer Currency": "PHP", "Currency of Proceeds": "PHP"},
        # refund of 1 unit in USD
        {"SKU": "premium.monthly", "Parent Identifier": "com.bticket.app", "Product Type Identifier": "IAY", "Units": "-1", "Developer Proceeds": "2.55", "Customer Price": "2.99", "Customer Currency": "USD", "Currency of Proceeds": "USD"},
        # someone else's app
        {"SKU": "other.sub", "Parent Identifier": "com.other.app", "Product Type Identifier": "IAY", "Units": "99", "Developer Proceeds": "100", "Customer Price": "100", "Customer Currency": "PHP", "Currency of Proceeds": "PHP"},
    ])
    r = AppleRevenueClient(apple_config, FX).parse_tsv(tsv, date(2026, 9, 1))
    assert r.transactions == 3 and r.refunds == 1
    assert r.gross == pytest.approx(450 - 2.99 * 56, abs=0.01)
    assert r.net == pytest.approx(382.5 - 2.55 * 56, abs=0.01)
    assert r.native_gross == {"PHP": 450.0, "USD": -2.99}


@responses.activate
def test_apple_daily_falls_back_on_404_then_monthly_sets_period(apple_config):
    url = "https://api.appstoreconnect.apple.com/v1/salesReports"
    responses.add(responses.GET, url, status=404)
    responses.add(responses.GET, url, body=_apple_tsv([
        {"SKU": "p", "Parent Identifier": "com.bticket.app", "Product Type Identifier": "IA9", "Units": "2", "Developer Proceeds": "85", "Customer Price": "100", "Customer Currency": "PHP", "Currency of Proceeds": "PHP"},
    ]), status=200)
    c = AppleRevenueClient(apple_config, FX)
    c._generate_jwt = lambda: "test-jwt"  # conftest key is a placeholder
    r = c.fetch_daily(date(2026, 9, 2))
    assert r.ok and r.period_start == date(2026, 9, 1) and r.gross == 200

    responses.add(responses.GET, url, body=_apple_tsv([]), status=200)
    m = c.fetch_month(2026, 8)
    assert m.period_start == date(2026, 8, 1) and m.period_end == date(2026, 8, 31)
    assert m.basis == "reconciled" and m.gross == 0


# ----------------------------------------------------------------------- google
def _zip_csv(name, header, rows, encoding="utf-8"):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    data = buf.getvalue().encode(encoding)
    if encoding == "utf-16":
        pass  # python adds BOM for utf-16
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as zf:
        zf.writestr(name, data)
    return zbuf.getvalue()


def _gp_client(google_play_config, blobs: dict):
    client = MagicMock()
    def blob_get(path):
        b = MagicMock()
        if path in blobs:
            b.download_as_bytes.return_value = blobs[path]
        else:
            b.download_as_bytes.side_effect = Exception("404 not found")
        return b
    client.bucket.return_value.blob.side_effect = blob_get
    listing = []
    for p in blobs:
        m = MagicMock(); m.name = p; listing.append(m)
    client.list_blobs.side_effect = lambda bucket, prefix="": [b for b in listing if b.name.startswith(prefix)]
    return GooglePlayRevenueClient(google_play_config, REV, FX, client=client)


def test_google_sales_daily_estimate_handles_utf16_and_refunds(google_play_config):
    header = ["Order Number", "Order Charged Date", "Financial Status", "Product Title", "Package ID", "Product Type",
              "SKU ID", "Currency of Sale", "Item Price", "Taxes Collected", "Charged Amount", "Country of Buyer"]
    rows = [
        ["1", "2026-09-01", "Charged", "Premium", "com.bticket.app", "subscription", "prem", "PHP", "150.00", "16.07", "150.00", "PH"],
        ["2", "2026-09-01", "Charged", "Premium", "com.bticket.app", "subscription", "prem", "USD", "2.99", "0.00", "2.99", "US"],
        ["3", "2026-09-01", "Refund", "Premium", "com.bticket.app", "subscription", "prem", "PHP", "150.00", "16.07", "150.00", "PH"],
        ["4", "2026-09-01", "Charged", "Other", "com.other.app", "subscription", "x", "PHP", "999", "0", "999", "PH"],
        ["5", "2026-08-31", "Charged", "Premium", "com.bticket.app", "subscription", "prem", "PHP", "150.00", "16.07", "150.00", "PH"],
    ]
    blobs = {"sales/salesreport_202609.zip": _zip_csv("salesreport_202609.csv", header, rows, "utf-16")}
    c = _gp_client(google_play_config, blobs)
    r = c.fetch_daily(date(2026, 9, 1))
    assert r.ok and r.transactions == 2 and r.refunds == 1
    assert r.gross == pytest.approx(2.99 * 56, abs=0.01)           # 150 - 150 + 2.99 USD
    assert r.net == pytest.approx((2.99 * 56) * 0.85, abs=0.01)     # tax nets to 0, 15% fee
    assert r.basis == "estimate"

    missing = c.fetch_daily(date(2026, 7, 1))
    assert not missing.ok and missing.error_message is None and "no Play sales export" in missing.note


def test_google_earnings_month_reconciles_ledger(google_play_config):
    header = ["Description", "Transaction Date", "Transaction Type", "Product Title", "Package ID", "Merchant Currency", "Amount (Merchant Currency)"]
    rows = [
        ["o1", "Aug 3, 2026", "Charge", "Premium", "com.bticket.app", "PHP", "150.00"],
        ["o1", "Aug 3, 2026", "Google fee", "Premium", "com.bticket.app", "PHP", "-22.50"],
        ["o1", "Aug 3, 2026", "Tax", "Premium", "com.bticket.app", "PHP", "-16.07"],
        ["o2", "Aug 9, 2026", "Charge", "Premium", "com.bticket.app", "PHP", "150.00"],
        ["o2", "Aug 9, 2026", "Google fee", "Premium", "com.bticket.app", "PHP", "-22.50"],
        ["o2", "Aug 20, 2026", "Charge refund", "Premium", "com.bticket.app", "PHP", "-150.00"],
        ["o2", "Aug 20, 2026", "Google fee refund", "Premium", "com.bticket.app", "PHP", "22.50"],
    ]
    blobs = {"earnings/earnings_202608_1234-5678.zip": _zip_csv("earnings_202608.csv", header, rows)}
    r = _gp_client(google_play_config, blobs).fetch_month(2026, 8)
    assert r.ok and r.basis == "reconciled"
    assert r.gross == pytest.approx(150.0)      # 150 + 150 - 150
    assert r.net == pytest.approx(150 - 22.5 - 16.07 + 150 - 22.5 - 150 + 22.5)
    assert r.transactions == 2 and r.refunds == 1

    none = _gp_client(google_play_config, {}).fetch_month(2026, 9)
    assert not none.ok and "not published" in none.note


# ----------------------------------------------------------------------- huawei
def test_huawei_parses_configured_columns_and_converts(huawei_config):
    c = HuaweiRevenueClient(huawei_config, REV, FX)
    text = "Date,Paid orders,Paid amount,Paying users\n20260901,4,120.00,3\n20260902,1,30.00,1\n"
    r = c.parse_csv(text, date(2026, 9, 1), date(2026, 9, 1), date(2026, 9, 1))
    assert r.ok and r.transactions == 4
    assert r.gross == pytest.approx(120 * 7.8) and r.net == pytest.approx(120 * 7.8 * 0.85)
    assert r.native_gross == {"CNY": 120.0}

    bad = c.parse_csv("Date,Something\n20260901,1\n", date(2026, 9, 1), date(2026, 9, 1), date(2026, 9, 1))
    assert bad.error_message and "HUAWEI_IAP_AMOUNT_COLUMN" in bad.error_message

    empty = c.parse_csv("", date(2026, 9, 1), date(2026, 9, 1), date(2026, 9, 1))
    assert not empty.ok and empty.error_message is None


# ---------------------------------------------------------------------- history
def test_history_upsert_and_period_totals(tmp_path):
    path = str(tmp_path / "revenue.csv")
    a = RevenueResult("App Store", date(2026, 9, 1), date(2026, 9, 1), gross=450, net=382.5, transactions=3)
    g = RevenueResult("Google Play", date(2026, 9, 1), date(2026, 9, 1), gross=300, net=255, transactions=2)
    bad = RevenueResult("Huawei", date(2026, 9, 1), date(2026, 9, 1), error_message="boom")
    assert upsert_daily([a, g, bad], fetched_on=date(2026, 9, 2), path=path) == 2
    # revision: Apple corrects the day upward
    a2 = RevenueResult("App Store", date(2026, 9, 1), date(2026, 9, 1), gross=600, net=510, transactions=4)
    assert upsert_daily([a2, g], fetched_on=date(2026, 9, 3), path=path) == 1   # google unchanged → skipped
    totals = period_totals(date(2026, 9, 1), date(2026, 9, 30), path=path)
    assert totals["appstore"]["net"] == 510 and totals["googleplay"]["gross"] == 300
    assert sum(1 for _ in open(path)) == 3  # header + 2 rows, no duplicates


def test_monthly_upsert(tmp_path):
    path = str(tmp_path / "m.csv")
    r = RevenueResult("App Store", date(2026, 8, 1), date(2026, 8, 31), gross=1000, net=850, basis="reconciled")
    upsert_monthly([r], path=path)
    upsert_monthly([r], path=path)
    rows = monthly_rows(path)
    assert len(rows) == 1 and rows[0]["month"] == "2026-08" and rows[0]["basis"] == "reconciled"


# -------------------------------------------------------------------- formatter
def test_daily_message_is_bilingual_and_under_telegram_limit():
    now = datetime(2026, 9, 3, 19, 0)
    results = [
        RevenueResult("App Store", date(2026, 9, 2), date(2026, 9, 2), gross=1500, net=1275, transactions=10),
        RevenueResult("Google Play", date(2026, 9, 2), date(2026, 9, 2), note="no Play sales export for 202609 yet"),
        RevenueResult("Huawei", date(2026, 9, 2), date(2026, 9, 2), error_message="500"),
    ]
    mtd = {"appstore": {"gross": 3000.0, "net": 2550.0, "transactions": 20, "refunds": 0, "days": 2}}
    msg = format_daily(results, now, mtd, data_date=date(2026, 9, 2))
    assert msg.startswith("<pre>") and msg.endswith("</pre>")
    assert "₱1,275" in msg and "MTD: ₱3,000 gross" in msg
    assert "⏳ no Play sales export" in msg and "⚠️ Unavailable" in msg
    assert "日次売上レポート" in msg and "取得不可" in msg
    assert len(msg) < 4096


def test_monthly_caption_fits_telegram_cap():
    results = [
        RevenueResult("App Store", date(2026, 8, 1), date(2026, 8, 31), gross=50000, net=42500, basis="reconciled"),
        RevenueResult("Google Play", date(2026, 8, 1), date(2026, 8, 31), gross=30000, net=24000, basis="reconciled"),
        RevenueResult("Huawei", date(2026, 8, 1), date(2026, 8, 31), gross=2000, net=1700, basis="estimate"),
    ]
    cap = format_monthly_caption(results, "August 2026", prev_net=60000)
    assert "▲ +13.7%" in cap and "(est.)" in cap and "月次売上" in cap
    assert len(cap) <= 1024


# -------------------------------------------------------------------------- pdf
def test_pdf_builds_with_partial_data(tmp_path):
    results = [
        RevenueResult("App Store", date(2026, 8, 1), date(2026, 8, 31), gross=50000, net=42500, transactions=300, refunds=4, basis="reconciled", native_gross={"PHP": 48000, "USD": 35.7}),
        RevenueResult("Google Play", date(2026, 8, 1), date(2026, 8, 31), gross=30000, net=24000, transactions=200, basis="reconciled", note="fees 4,500 · tax 1,500 (PHP ledger)"),
        RevenueResult("Huawei", date(2026, 8, 1), date(2026, 8, 31), note="no Huawei IAP rows for period"),
    ]
    daily = [{"report_date": date(2026, 8, d), "platform": "appstore", "gross": 1600.0, "net": 1370.0, "transactions": 10, "refunds": 0} for d in range(1, 32)]
    daily += [{"report_date": date(2026, 8, d), "platform": "googleplay", "gross": 1000.0, "net": 800.0, "transactions": 6, "refunds": 0} for d in range(1, 32)]
    hist = [
        {"month": "2026-06", "platform": "appstore", "gross": 40000, "net": 34000, "transactions": 1, "refunds": 0, "basis": "reconciled"},
        {"month": "2026-07", "platform": "appstore", "gross": 45000, "net": 38250, "transactions": 1, "refunds": 0, "basis": "reconciled"},
        {"month": "2026-07", "platform": "googleplay", "gross": 25000, "net": 20000, "transactions": 1, "refunds": 0, "basis": "reconciled"},
        {"month": "2026-08", "platform": "appstore", "gross": 50000, "net": 42500, "transactions": 1, "refunds": 0, "basis": "reconciled"},
        {"month": "2026-08", "platform": "googleplay", "gross": 30000, "net": 24000, "transactions": 1, "refunds": 0, "basis": "reconciled"},
    ]
    out = str(tmp_path / "r.pdf")
    build_monthly_pdf(out, results, 2026, 8, daily, hist, prev_net=58250, generated=datetime(2026, 9, 6, 9, 0))
    assert os.path.getsize(out) > 5000
    with open(out, "rb") as fh:
        assert fh.read(5) == b"%PDF-"
