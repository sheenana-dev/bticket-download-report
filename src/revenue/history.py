"""CSV persistence for revenue — same pattern as src/history.py.

data/revenue.csv          one row per (report_date, platform) — daily estimates
data/revenue_monthly.csv  one row per (month, platform)       — reconciled

Rows are upserted (later fetch wins) because both Apple and Google revise
recent days; the running MTD/YTD are computed at read time, never stored.
"""

import csv
import logging
import os
import tempfile
from datetime import date
from typing import Iterable, Optional

from src.revenue.models import RevenueResult

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
DAILY_PATH = os.path.join(DATA_DIR, "revenue.csv")
MONTHLY_PATH = os.path.join(DATA_DIR, "revenue_monthly.csv")

DAILY_HEADERS = ["fetched_on", "report_date", "platform", "gross", "net", "transactions", "refunds", "trials", "basis", "native_gross"]
MONTHLY_HEADERS = ["fetched_on", "month", "platform", "gross", "net", "transactions", "refunds", "basis", "note"]

PLATFORM_KEY = {"App Store": "appstore", "Google Play": "googleplay", "Huawei": "huawei"}
STORE_NAME = {v: k for k, v in PLATFORM_KEY.items()}


def _read(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def _write_atomic(path: str, headers: list[str], rows: Iterable[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _native_str(native: dict) -> str:
    return ";".join(f"{k}:{v:.2f}" for k, v in sorted(native.items()))


def upsert_daily(results: list[RevenueResult], fetched_on: Optional[date] = None,
                 path: str = DAILY_PATH) -> int:
    """Insert or replace daily rows. Returns number of rows written/updated."""
    fetched_on = fetched_on or date.today()
    rows = _read(path)
    index = {(r["report_date"], r["platform"]): i for i, r in enumerate(rows)}
    changed = 0
    for r in results:
        if not r.ok or r.period_start != r.period_end:
            continue
        platform = PLATFORM_KEY.get(r.store_name)
        if not platform:
            continue
        row = {
            "fetched_on": fetched_on.isoformat(),
            "report_date": r.period_start.isoformat(),
            "platform": platform,
            "gross": f"{r.gross:.2f}",
            "net": f"{(r.net if r.net is not None else 0.0):.2f}",
            "transactions": str(r.transactions or 0),
            "refunds": str(r.refunds or 0),
            "trials": str(r.trials or 0),
            "basis": r.basis,
            "native_gross": _native_str(r.native_gross),
        }
        key = (row["report_date"], platform)
        if key in index:
            if {k: rows[index[key]].get(k) for k in row if k != "fetched_on"} == {k: v for k, v in row.items() if k != "fetched_on"}:
                continue
            rows[index[key]] = row
        else:
            rows.append(row)
            index[key] = len(rows) - 1
        changed += 1
    if changed:
        rows.sort(key=lambda r: (r["report_date"], r["platform"]))
        _write_atomic(path, DAILY_HEADERS, rows)
        logger.info("Revenue history: %d row(s) upserted -> %s", changed, path)
    return changed


def upsert_monthly(results: list[RevenueResult], fetched_on: Optional[date] = None,
                   path: str = MONTHLY_PATH) -> int:
    fetched_on = fetched_on or date.today()
    rows = _read(path)
    index = {(r["month"], r["platform"]): i for i, r in enumerate(rows)}
    changed = 0
    for r in results:
        if not r.ok:
            continue
        platform = PLATFORM_KEY.get(r.store_name)
        if not platform:
            continue
        row = {
            "fetched_on": fetched_on.isoformat(),
            "month": r.period_start.strftime("%Y-%m"),
            "platform": platform,
            "gross": f"{r.gross:.2f}",
            "net": f"{(r.net if r.net is not None else 0.0):.2f}",
            "transactions": str(r.transactions or 0),
            "refunds": str(r.refunds or 0),
            "basis": r.basis,
            "note": r.note or "",
        }
        key = (row["month"], platform)
        if key in index:
            rows[index[key]] = row
        else:
            rows.append(row)
            index[key] = len(rows) - 1
        changed += 1
    if changed:
        rows.sort(key=lambda r: (r["month"], r["platform"]))
        _write_atomic(path, MONTHLY_HEADERS, rows)
    return changed


def daily_rows(path: str = DAILY_PATH) -> list[dict]:
    out = []
    for r in _read(path):
        try:
            out.append({
                "report_date": date.fromisoformat(r["report_date"]),
                "platform": r["platform"],
                "gross": float(r["gross"]),
                "net": float(r["net"]),
                "transactions": int(r.get("transactions") or 0),
                "refunds": int(r.get("refunds") or 0),
                "trials": int(r.get("trials") or 0),
            })
        except (KeyError, ValueError):
            continue
    return out


def period_totals(start: date, end: date, path: str = DAILY_PATH) -> dict[str, dict]:
    """Sum daily rows per platform over [start, end] (inclusive)."""
    totals: dict[str, dict] = {}
    for r in daily_rows(path):
        if start <= r["report_date"] <= end:
            t = totals.setdefault(r["platform"], {"gross": 0.0, "net": 0.0, "transactions": 0, "refunds": 0, "trials": 0, "days": 0})
            t["gross"] += r["gross"]
            t["net"] += r["net"]
            t["transactions"] += r["transactions"]
            t["refunds"] += r["refunds"]
            t["trials"] += r["trials"]
            t["days"] += 1
    return totals


def monthly_rows(path: str = MONTHLY_PATH) -> list[dict]:
    out = []
    for r in _read(path):
        try:
            out.append({
                "month": r["month"],
                "platform": r["platform"],
                "gross": float(r["gross"]),
                "net": float(r["net"]),
                "transactions": int(r.get("transactions") or 0),
                "refunds": int(r.get("refunds") or 0),
                "basis": r.get("basis", ""),
            })
        except (KeyError, ValueError):
            continue
    return out
