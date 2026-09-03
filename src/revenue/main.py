"""Revenue report entry point.

    python -m src.revenue.main daily   [--date YYYY-MM-DD] [--dry-run]
    python -m src.revenue.main monthly [--month YYYY-MM]   [--dry-run] [--out reports/]
    python -m src.revenue.main probe   huawei|apple|google [--date YYYY-MM-DD]

`daily` fetches yesterday (PHT) from all three stores, upserts data/revenue.csv,
and posts the bilingual Telegram summary. It also re-fetches the previous 7
days so late-posting stores (Google's 3–7 day lag, Apple revisions) back-fill
themselves — same self-healing idea as the download report's reconcile.

`monthly` builds the reconciled PDF for the previous month (or --month) and
sends it as a Telegram document with a short caption.

`probe` dumps the raw export headers/rows so column names can be pinned
without guessing (needed once for Huawei).
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.config import AppConfig, load_config
from src.revenue.apple import AppleRevenueClient
from src.revenue.formatter import format_daily, format_monthly_caption
from src.revenue.fx import FxConverter
from src.revenue.google_play import GooglePlayRevenueClient
from src.revenue.history import (
    PLATFORM_KEY, daily_rows, monthly_rows, period_totals, upsert_daily, upsert_monthly,
)
from src.revenue.huawei import HuaweiRevenueClient
from src.revenue.models import RevenueResult
from src.revenue.pdf import build_monthly_pdf
from src.telegram import send_telegram_document, send_telegram_message
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)

BACKFILL_DAYS = 7


def _clients(config: AppConfig, fx: FxConverter) -> list:
    clients = [
        AppleRevenueClient(config.apple, fx),
        GooglePlayRevenueClient(config.google_play, config.revenue, fx),
    ]
    if config.huawei:
        clients.append(HuaweiRevenueClient(config.huawei, config.revenue, fx))
    else:
        logger.warning("HUAWEI_* not set — Huawei revenue skipped")
    return clients


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


# --------------------------------------------------------------------------- daily
def run_daily(config: AppConfig, now: datetime, target: Optional[date], dry_run: bool) -> int:
    fx = FxConverter(config.revenue.report_currency, config.revenue.fx_overrides)
    clients = _clients(config, fx)
    target = target or (now - timedelta(days=1)).date()
    logger.info("Revenue daily — target %s", target)

    results: list[RevenueResult] = []
    for c in clients:
        results.append(c.fetch_daily(target))

    # Self-heal: refresh the trailing week so late exports/revisions land.
    # A store whose target-day fetch errored (auth, network) is skipped — no
    # point burning 7 more retry cycles against a dead endpoint.
    backfill: list[RevenueResult] = []
    dead = {r.store_name for r in results if r.error_message}
    for c in clients:
        if c.store_name in dead:
            logger.warning("%s errored on target day — skipping backfill", c.store_name)
            continue
        for back in range(1, BACKFILL_DAYS + 1):
            d = target - timedelta(days=back)
            try:
                r = c.fetch_daily(d)
                if r.ok:
                    backfill.append(r)
            except Exception as e:  # noqa: BLE001
                logger.warning("backfill %s %s failed: %s", c.store_name, d, e)

    try:
        n = upsert_daily(results + backfill, fetched_on=now.date())
        logger.info("Revenue history: %d row(s) changed", n)
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to persist revenue history (non-fatal): %s", e)

    # Data date = the day most stores actually returned; MTD = that month so far.
    data_date = next((r.period_start for r in results if r.ok), target)
    mtd = period_totals(data_date.replace(day=1), data_date)
    message = format_daily(results, now, mtd, config.revenue.report_currency, data_date=data_date)
    logger.info("Report:\n%s", message)

    if dry_run:
        logger.info("Dry run — skipping Telegram send")
        return 0
    ok = send_telegram_message(config.telegram, message, chat_id=config.revenue.chat_id)
    return 0 if ok else 1


# ------------------------------------------------------------------------- monthly
def backfill_month_daily(clients: list, year: int, month: int, now: datetime) -> int:
    """Fetch every day of the month per store into data/revenue.csv.

    Makes the PDF's daily chart meaningful from the first run and seeds the
    history the daily job then keeps current. Apple = one request per day
    (well inside the ~200/hr limit); Google reuses the cached monthly zip;
    Huawei is one range call per day.
    """
    from calendar import monthrange
    rows: list[RevenueResult] = []
    last = min(date(year, month, monthrange(year, month)[1]), now.date() - timedelta(days=1))
    for c in clients:
        d = date(year, month, 1)
        failures = 0
        while d <= last:
            r = c.fetch_daily(d)
            if r.ok:
                rows.append(r)
            elif r.error_message:
                failures += 1
                if failures >= 3:
                    logger.warning("%s: 3 errors during month backfill — stopping", c.store_name)
                    break
            d += timedelta(days=1)
    return upsert_daily(rows, fetched_on=now.date())


def run_monthly(config: AppConfig, now: datetime, month: Optional[str], out_dir: str, dry_run: bool,
                daily_backfill: bool = True) -> int:
    if month:
        year, mon = (int(x) for x in month.split("-"))
    else:
        year, mon = _prev_month(now.year, now.month)
    ccy = config.revenue.report_currency
    fx = FxConverter(ccy, config.revenue.fx_overrides)
    clients = _clients(config, fx)
    logger.info("Revenue monthly — %04d-%02d", year, mon)

    if daily_backfill:
        try:
            n = backfill_month_daily(clients, year, mon, now)
            logger.info("Month daily backfill: %d row(s) upserted", n)
        except Exception as e:  # noqa: BLE001
            logger.warning("Daily backfill for month failed (non-fatal): %s", e)

    results = [c.fetch_month(year, mon) for c in clients]

    # A store whose reconciled report isn't published yet (Google's ledger lands
    # ~5th, Apple's monthly a few days in) would otherwise show "Unavailable" and
    # drop out of the totals — while the daily chart below still shows its sales.
    # Fall back to the sum of that store's daily estimate rows, clearly labelled,
    # so the month total is complete; the next run swaps in the reconciled figure.
    from calendar import monthrange
    m_start, m_end = date(year, mon, 1), date(year, mon, monthrange(year, mon)[1])
    totals = period_totals(m_start, m_end)
    for i, r in enumerate(results):
        if r.ok or r.error_message:
            continue
        key = PLATFORM_KEY.get(r.store_name)
        t = totals.get(key)
        if not t or not t["days"]:
            continue
        results[i] = RevenueResult(
            store_name=r.store_name, period_start=m_start, period_end=m_end,
            gross=round(t["gross"], 2), net=round(t["net"], 2),
            transactions=t["transactions"], refunds=t["refunds"], basis="estimate",
            note=f"{r.note or 'reconciled report not published yet'} — sum of {t['days']} daily estimate rows",
        )
        logger.info("%s: monthly report not published; using daily estimate sum", r.store_name)

    try:
        upsert_monthly(results, fetched_on=now.date())
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to persist monthly revenue (non-fatal): %s", e)

    history = monthly_rows()
    py, pm = _prev_month(year, mon)
    prev_net = sum(r["net"] for r in history if r["month"] == f"{py:04d}-{pm:02d}") or None

    os.makedirs(out_dir, exist_ok=True)
    pdf_path = os.path.join(out_dir, f"bticket-revenue-{year:04d}-{mon:02d}.pdf")
    build_monthly_pdf(pdf_path, results, year, mon, daily_rows(), history, prev_net, ccy, generated=now)
    logger.info("PDF written: %s", pdf_path)

    month_label = date(year, mon, 1).strftime("%B %Y")
    caption = format_monthly_caption(results, month_label, ccy, prev_net)
    logger.info("Caption:\n%s", caption)

    if dry_run:
        logger.info("Dry run — skipping Telegram send (would go to %s)",
                    ", ".join(config.revenue.monthly_chat_ids) or config.revenue.chat_id or config.telegram.chat_id)
        return 0
    # Monthly PDF goes to REVENUE_MONTHLY_CHAT_ID (e.g. the CEO directly); if that
    # is unset it follows the daily revenue chat, then the download chat.
    recipients = list(config.revenue.monthly_chat_ids) or [config.revenue.chat_id or config.telegram.chat_id]
    ok = True
    for chat in recipients:
        ok = send_telegram_document(config.telegram, pdf_path, caption, chat_id=chat) and ok
    return 0 if ok else 1


# --------------------------------------------------------------------------- probe
def run_probe(config: AppConfig, store: str, target: date) -> int:
    """Print raw export headers + first rows. No parsing, no Telegram."""
    import csv
    import gzip
    import io

    fx = FxConverter(config.revenue.report_currency, config.revenue.fx_overrides)
    if store == "huawei":
        if not config.huawei:
            print("HUAWEI_* env not set")
            return 1
        c = HuaweiRevenueClient(config.huawei, config.revenue, fx)
        text = c.fetch_csv(target, target)
        print(f"--- Huawei IAP export {target} via {config.revenue.huawei_iap_report_path}")
        print(text[:3000] if text else "(empty — no fileURL returned; try an earlier date or another path)")
    elif store == "apple":
        c = AppleRevenueClient(config.apple, fx)
        raw = c._fetch("DAILY", target.strftime("%Y-%m-%d"))  # noqa: SLF001
        text = gzip.decompress(raw).decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
        print(f"--- Apple SALES DAILY {target}: {len(rows)} rows")
        if rows:
            print("columns:", list(rows[0].keys()))
        for r in rows[:40]:
            print({k: r[k] for k in ("SKU", "Parent Identifier", "Product Type Identifier", "Units", "Customer Price", "Customer Currency", "Developer Proceeds", "Currency of Proceeds") if k in r})
    elif store == "google":
        c = GooglePlayRevenueClient(config.google_play, config.revenue, fx)
        from src.revenue.google_play import _unzip_csv
        ym = target.strftime("%Y%m")
        raw = c._download(f"sales/salesreport_{ym}.zip")  # noqa: SLF001
        if raw is None:
            print(f"no sales/salesreport_{ym}.zip")
        else:
            rows = list(csv.DictReader(io.StringIO(_unzip_csv(raw))))
            print(f"--- Play sales {ym}: {len(rows)} rows; columns: {list(rows[0].keys()) if rows else []}")
            for r in rows[:15]:
                print(r)
        blob = c._find_earnings_blob(ym)  # noqa: SLF001
        print("earnings blob:", blob)
    else:
        print("store must be huawei|apple|google")
        return 2
    return 0


# ---------------------------------------------------------------------------- cli
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="src.revenue.main")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_daily = sub.add_parser("daily")
    p_daily.add_argument("--date", help="data date YYYY-MM-DD (default: yesterday PHT)")
    p_daily.add_argument("--dry-run", action="store_true")

    p_month = sub.add_parser("monthly")
    p_month.add_argument("--month", help="YYYY-MM (default: previous month)")
    p_month.add_argument("--out", default="reports")
    p_month.add_argument("--dry-run", action="store_true")
    p_month.add_argument("--skip-daily-backfill", action="store_true",
                         help="don't (re)fetch each day of the month into data/revenue.csv")

    p_probe = sub.add_parser("probe")
    p_probe.add_argument("store", choices=["huawei", "apple", "google"])
    p_probe.add_argument("--date", help="YYYY-MM-DD (default: 3 days ago)")

    args = parser.parse_args(argv)
    setup_logging()

    try:
        config = load_config()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        return 1

    now = datetime.now(ZoneInfo(config.timezone))

    if args.cmd == "daily":
        target = date.fromisoformat(args.date) if args.date else None
        return run_daily(config, now, target, args.dry_run)
    if args.cmd == "monthly":
        return run_monthly(config, now, args.month, args.out, args.dry_run,
                           daily_backfill=not args.skip_daily_backfill)
    if args.cmd == "probe":
        target = date.fromisoformat(args.date) if args.date else (now - timedelta(days=3)).date()
        return run_probe(config, args.store, target)
    return 2


if __name__ == "__main__":
    sys.exit(main())
