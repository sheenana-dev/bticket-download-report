"""Revenue formatting: currency helper + the monthly PDF caption.

The daily revenue figures are rendered inside the combined daily message
(src.combined_report).
"""

from typing import Optional

from src.revenue.models import RevenueResult

ICONS = {"App Store": "\U0001f34e", "Google Play": "\U0001f916", "Huawei": "\U0001f4f1"}
SYMBOL = {"PHP": "₱", "USD": "$", "JPY": "¥", "KRW": "₩", "EUR": "€"}


def money(value: Optional[float], ccy: str = "PHP") -> str:
    if value is None:
        return "N/A"
    sym = SYMBOL.get(ccy.upper(), ccy.upper() + " ")
    return f"{sym}{value:,.0f}"


def format_monthly_caption(results: list[RevenueResult], month_label: str, ccy: str = "PHP",
                           prev_net: Optional[float] = None) -> str:
    """Short HTML caption for the PDF document (Telegram caps captions at 1024 chars)."""
    net = sum(r.net or 0.0 for r in results if r.ok)
    gross = sum(r.gross or 0.0 for r in results if r.ok)
    lines = [
        f"<b>\U0001f4b0 B-Ticket Monthly Revenue — {month_label}</b>",
        f"Net {money(net, ccy)} · Gross {money(gross, ccy)}",
    ]
    if prev_net:
        delta = (net - prev_net) / prev_net * 100 if prev_net else 0.0
        arrow = "▲" if delta >= 0 else "▼"
        lines.append(f"{arrow} {delta:+.1f}% vs prior month")
    for r in results:
        icon = ICONS.get(r.store_name, "\U0001f4e6")
        if r.ok:
            tag = "" if r.basis == "reconciled" else " (est.)"
            lines.append(f"{icon} {r.store_name}: {money(r.net, ccy)}{tag}")
        else:
            lines.append(f"{icon} {r.store_name}: ⚠️ {r.note or 'unavailable'}")
    lines.append("")
    lines.append(f"\U0001f4b0 {month_label} 月次売上：純額 {money(net, ccy)}／総額 {money(gross, ccy)}")
    lines.append("詳細は添付PDFをご確認ください。")
    return "\n".join(lines)
