"""One compact bilingual Telegram message: downloads + net revenue.

Store names and numbers read the same in English and Japanese, so a single
block with bilingual section headers replaces the two full EN+JA reports
(~100 lines -> ~15). Gross revenue and the reconciled figures stay in the
monthly PDF.
"""

from datetime import datetime
from typing import Optional

from src.formatter import fmt_count, stale_flag
from src.revenue.formatter import money
from src.revenue.history import PLATFORM_KEY
from src.revenue.models import DailyRevenue, RevenueResult
from src.stores.base import StoreResult

STORE_LABEL = {"App Store": "🍎 iOS", "Google Play": "🤖 Android", "Huawei": "📱 Huawei"}
# Net for these is gross minus a configured fee rate, not store-reported.
ESTIMATED = {"Google Play", "Huawei"}
LABEL_W = 11
VALUE_W = 13
UNAVAILABLE = "⚠️ unavailable 取得不可"


def _label(store_name: str) -> str:
    return STORE_LABEL.get(store_name, f"📦 {store_name}")


def _row(label: str, value: str, note: str = "") -> str:
    return f"{label:<{LABEL_W}}{value:<{VALUE_W}}{note}".rstrip()


def _download_note(r: StoreResult) -> str:
    stale = stale_flag(r)
    note = f"·{r.data_date}" if r.data_date else ""
    return note + (f" ⚠️{stale}d" if stale is not None else "")


def _download_lines(results: Optional[list[StoreResult]]) -> list[str]:
    if results is None:
        return ["📥 Downloads ダウンロード", f"   {UNAVAILABLE}"]

    lines = ["📥 Downloads ダウンロード (today/total)"]
    day_total, grand_total = 0, 0
    for r in results:
        if r.error_message and r.daily_downloads is None:
            lines.append(_row(_label(r.store_name), UNAVAILABLE))
            continue
        value = f"{fmt_count(r.daily_downloads)} / {fmt_count(r.total_downloads)}"
        lines.append(_row(_label(r.store_name), value, _download_note(r)))
        if r.total_uninstalls is not None:
            lines.append(f"   churn 解約 {fmt_count(r.daily_uninstalls)} / {fmt_count(r.total_uninstalls)}")
        day_total += r.daily_downloads or 0
        grand_total += r.total_downloads or 0
    lines.append(_row("📦 Total", f"{fmt_count(day_total)} / {fmt_count(grand_total)}"))
    return lines


def _revenue_counts(r: RevenueResult, mtd: dict) -> str:
    bits = []
    if r.transactions:
        bits.append(f"{r.transactions} paid")
    if r.refunds:
        bits.append(f"{r.refunds} refund")
    if mtd.get("trials"):
        bits.append(f"{mtd['trials']} trial MTD")
    return " · ".join(bits)


def _revenue_row(r: RevenueResult, mtd: dict, ccy: str) -> str:
    if r.error_message:
        return _row(_label(r.store_name), UNAVAILABLE)
    today = money(r.net, ccy) if r.net is not None else "⏳"
    month = money(mtd["net"], ccy) if mtd else "–"
    star = "*" if r.store_name in ESTIMATED else ""
    return _row(_label(r.store_name), f"{today} / {month}{star}", _revenue_counts(r, mtd))


def _revenue_lines(rev: Optional[DailyRevenue]) -> list[str]:
    if rev is None:
        return ["💰 Net revenue 純売上", f"   {UNAVAILABLE}"]

    ccy = rev.currency
    lines = [f"💰 Net revenue 純売上 (today/MTD) ·{rev.data_date:%b %d}"]
    for r in rev.results:
        lines.append(_revenue_row(r, rev.mtd.get(PLATFORM_KEY.get(r.store_name, ""), {}), ccy))

    any_ok = any(r.net is not None and not r.error_message for r in rev.results)
    day_net = sum(r.net or 0.0 for r in rev.results if not r.error_message)
    mtd_net = sum(v["net"] for v in rev.mtd.values())
    lines.append(_row("📦 Total", f"{money(day_net if any_ok else None, ccy)} / {money(mtd_net, ccy)}"))
    if any(r.store_name in ESTIMATED for r in rev.results):
        lines += ["", "* est. 推定 · final in monthly PDF 月次PDFで確定"]
    return lines


def format_combined(
    downloads: Optional[list[StoreResult]],
    revenue: Optional[DailyRevenue],
    report_time: datetime,
) -> str:
    """Render the combined daily message. A None section = collection failed."""
    lines = [
        "📊 B-Ticket Daily · 日次レポート",
        f"📅 {report_time:%b %d} · {report_time:%I:%M %p} PHT",
        "",
        *_download_lines(downloads),
        "",
        *_revenue_lines(revenue),
    ]
    return "<pre>" + "\n".join(lines) + "</pre>"
