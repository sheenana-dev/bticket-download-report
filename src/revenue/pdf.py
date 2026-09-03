"""Monthly revenue PDF (reportlab, no external assets).

One A4 page, two if the daily table is long: header band, KPI tiles, per-store
reconciliation table, daily net bar chart, 6-month trend, methodology, and a
Japanese executive summary for Kento-san / Mura-san.
"""

import logging
import os
from datetime import date, datetime
from typing import Optional

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether,
)

from src.revenue.formatter import money
from src.revenue.models import RevenueResult

# B-Ticket brand
GREEN_DARK = colors.HexColor("#205C50")
GREEN = colors.HexColor("#56A66F")
GREEN_LIGHT = colors.HexColor("#84BEA1")
YELLOW = colors.HexColor("#F1E048")
INK = colors.HexColor("#1F2A26")
MUTED = colors.HexColor("#6B7A75")
RULE = colors.HexColor("#DDE7E2")
PAPER = colors.white

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FONT_DIR = os.path.join(REPO_ROOT, "assets", "fonts")

# Resolved at register time. Poppins (brand) for headings — bundled in the
# repo. DejaVu Sans for figures because Helvetica has no ₱ glyph. IPA Gothic
# for Japanese (TrueType, so it embeds cleanly); the workflow apt-installs it
# and we fall back to reportlab's built-in CID font if it's missing.
FONTS = {"head": "Helvetica-Bold", "body": "Helvetica", "body_b": "Helvetica-Bold", "jp": "HeiseiKakuGo-W5"}

_CANDIDATES = {
    "head": [os.path.join(FONT_DIR, "Poppins-Bold.ttf")],
    "body": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", os.path.join(FONT_DIR, "DejaVuSans.ttf")],
    "body_b": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")],
    "jp": [
        os.path.join(FONT_DIR, "ipagp.ttf"),
        "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
        "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    ],
}
_NAMES = {"head": "Poppins-Bold", "body": "DejaVuSans", "body_b": "DejaVuSans-Bold", "jp": "IPAPGothic"}


def _register_fonts() -> None:
    registered = set(pdfmetrics.getRegisteredFontNames())
    for role, paths in _CANDIDATES.items():
        name = _NAMES[role]
        if name in registered:
            FONTS[role] = name
            continue
        for p in paths:
            if os.path.exists(p):
                try:
                    pdfmetrics.registerFont(TTFont(name, p))
                    FONTS[role] = name
                    break
                except Exception as e:  # noqa: BLE001 — fall back to core fonts
                    logger.warning("Could not register font %s from %s: %s", name, p, e)
    if FONTS["jp"] == "HeiseiKakuGo-W5" and "HeiseiKakuGo-W5" not in registered:
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    # Bold/italic mapping so <b> inside body paragraphs resolves.
    from reportlab.lib.fonts import addMapping
    if FONTS["body"] == "DejaVuSans":
        addMapping("DejaVuSans", 0, 0, "DejaVuSans")
        addMapping("DejaVuSans", 1, 0, FONTS["body_b"])
        addMapping("DejaVuSans", 0, 1, "DejaVuSans")
        addMapping("DejaVuSans", 1, 1, FONTS["body_b"])
    if FONTS["jp"] == "IPAPGothic":
        addMapping("IPAPGothic", 0, 0, "IPAPGothic")
        addMapping("IPAPGothic", 1, 0, "IPAPGothic")


def _styles() -> dict:
    body, body_b, head, jp = FONTS["body"], FONTS["body_b"], FONTS["head"], FONTS["jp"]
    return {
        "h2": ParagraphStyle("h2", fontName=head, fontSize=11.5, leading=15, textColor=GREEN_DARK, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("body", fontName=body, fontSize=9, leading=12, textColor=INK),
        "muted": ParagraphStyle("muted", fontName=body, fontSize=7.2, leading=9.5, textColor=MUTED),
        "kpi_label": ParagraphStyle("kl", fontName=head, fontSize=7, leading=9, textColor=MUTED),
        "kpi_value": ParagraphStyle("kv", fontName=body_b, fontSize=15, leading=18, textColor=GREEN_DARK),
        "kpi_delta": ParagraphStyle("kd", fontName=body, fontSize=7.5, leading=10, textColor=GREEN),
        "jp_h2": ParagraphStyle("jph2", fontName=jp, fontSize=11.5, leading=16, textColor=GREEN_DARK, spaceBefore=8, spaceAfter=4),
        "jp_body": ParagraphStyle("jpb", fontName=jp, fontSize=8.5, leading=13.5, textColor=INK),
        "cell": ParagraphStyle("cell", fontName=body, fontSize=8.5, leading=11, textColor=INK),
        "cell_r": ParagraphStyle("cellr", fontName=body, fontSize=8.5, leading=11, textColor=INK, alignment=TA_RIGHT),
        "cell_b": ParagraphStyle("cellb", fontName=body_b, fontSize=8.5, leading=11, textColor=INK),
        "cell_br": ParagraphStyle("cellbr", fontName=body_b, fontSize=8.5, leading=11, textColor=INK, alignment=TA_RIGHT),
    }


def _header(canvas, doc, month_label: str, generated: datetime) -> None:
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(GREEN_DARK)
    canvas.rect(0, h - 34 * mm, w, 34 * mm, stroke=0, fill=1)
    canvas.setFillColor(YELLOW)
    canvas.rect(0, h - 34 * mm, w, 1.5 * mm, stroke=0, fill=1)
    canvas.setFillColor(PAPER)
    canvas.setFont(FONTS["head"], 19)
    canvas.drawString(18 * mm, h - 17 * mm, "B-Ticket  ·  Monthly Revenue Report")
    canvas.setFont(FONTS["body"], 9)
    canvas.setFillColor(colors.HexColor("#D8EBE3"))
    canvas.drawString(18 * mm, h - 24 * mm, f"{month_label}   ·   In-app subscriptions & purchases · App Store / Google Play / Huawei")
    canvas.setFont(FONTS["body"], 8)
    canvas.drawRightString(w - 18 * mm, h - 15 * mm, f"Generated {generated:%Y-%m-%d %H:%M} PHT")
    # footer
    canvas.setFillColor(MUTED)
    canvas.setFont(FONTS["body"], 7)
    canvas.drawString(18 * mm, 10 * mm, "Auto-generated by AI from store exports. Reconciled = store-reported net; Est. = fee applied by rate. Confidential.")
    canvas.drawRightString(w - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _kpi_tiles(results: list[RevenueResult], prev_net: Optional[float], ccy: str, st: dict) -> Table:
    net = sum(r.net or 0 for r in results if r.ok)
    gross = sum(r.gross or 0 for r in results if r.ok)
    txns = sum(r.transactions or 0 for r in results if r.ok)
    refunds = sum(r.refunds or 0 for r in results if r.ok)
    take = (net / gross * 100) if gross else 0.0
    if prev_net:
        delta = (net - prev_net) / prev_net * 100
        delta_txt = f"{'▲' if delta >= 0 else '▼'} {delta:+.1f}% vs prior month"
    else:
        delta_txt = "no prior month on file"

    def tile(label, value, sub):
        return [Paragraph(label, st["kpi_label"]), Paragraph(value, st["kpi_value"]), Paragraph(sub, st["kpi_delta"])]

    data = [[
        tile("NET REVENUE", money(net, ccy), delta_txt),
        tile("GROSS BILLINGS", money(gross, ccy), f"take-home {take:.0f}%"),
        tile("TRANSACTIONS", f"{txns:,}", f"{refunds:,} refunds"),
        tile("STORES REPORTING", f"{sum(1 for r in results if r.ok)}/{len(results)}",
             ", ".join(r.store_name for r in results if not r.ok) or "all sources OK"),
    ]]
    t = Table(data, colWidths=[43.5 * mm] * 4, rowHeights=[21 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F8F6")),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _store_table(results: list[RevenueResult], ccy: str, st: dict) -> Table:
    head = ["Store", "Gross", "Net", "Txns", "Refunds", "Basis", "Notes"]
    rows = [[Paragraph(f"<b>{h}</b>", st["cell_r" if i in (1, 2, 3, 4) else "cell"]) for i, h in enumerate(head)]]
    for r in results:
        if r.ok:
            rows.append([
                Paragraph(r.store_name, st["cell_b"]),
                Paragraph(money(r.gross, ccy), st["cell_r"]),
                Paragraph(money(r.net, ccy), st["cell_br"]),
                Paragraph(f"{r.transactions or 0:,}", st["cell_r"]),
                Paragraph(f"{r.refunds or 0:,}", st["cell_r"]),
                Paragraph("Reconciled" if r.basis == "reconciled" else "Estimate", st["cell"]),
                Paragraph((r.note or "") + (" · native " + ", ".join(f"{k} {v:,.0f}" for k, v in r.native_gross.items()) if r.native_gross else ""), st["muted"]),
            ])
        else:
            rows.append([
                Paragraph(r.store_name, st["cell_b"]),
                Paragraph("—", st["cell_r"]), Paragraph("—", st["cell_r"]),
                Paragraph("—", st["cell_r"]), Paragraph("—", st["cell_r"]),
                Paragraph("Unavailable", st["cell"]),
                Paragraph(r.error_message or r.note or "", st["muted"]),
            ])
    net = sum(r.net or 0 for r in results if r.ok)
    gross = sum(r.gross or 0 for r in results if r.ok)
    rows.append([
        Paragraph("Total", st["cell_b"]),
        Paragraph(money(gross, ccy), st["cell_br"]),
        Paragraph(money(net, ccy), st["cell_br"]),
        Paragraph(f"{sum(r.transactions or 0 for r in results if r.ok):,}", st["cell_br"]),
        Paragraph(f"{sum(r.refunds or 0 for r in results if r.ok):,}", st["cell_br"]),
        "", "",
    ])
    t = Table(rows, colWidths=[27 * mm, 22 * mm, 22 * mm, 13 * mm, 18 * mm, 22 * mm, 50 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), PAPER),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, GREEN_DARK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [PAPER, colors.HexColor("#F7FAF9")]),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, GREEN_DARK),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF3EE")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    # header cells need white text: Paragraph styles override, so rebuild header row
    for i, h in enumerate(head):
        style = ParagraphStyle("hdr", parent=st["cell_r" if i in (1, 2, 3, 4) else "cell"], textColor=PAPER, fontName=FONTS["body_b"], fontSize=7)
        rows[0][i] = Paragraph(h, style)
    return t


def _daily_chart(daily: list[dict], year: int, month: int, ccy: str) -> Drawing:
    """Stacked daily net by store for the month."""
    from calendar import monthrange
    days = monthrange(year, month)[1]
    stores = ["appstore", "googleplay", "huawei"]
    series = {s: [0.0] * days for s in stores}
    for r in daily:
        d = r["report_date"]
        if d.year == year and d.month == month and r["platform"] in series:
            series[r["platform"]][d.day - 1] += r["net"]
    d = Drawing(174 * mm, 46 * mm)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 12 * mm, 7 * mm, 158 * mm, 33 * mm
    chart.data = [series[s] for s in stores]
    chart.categoryAxis.categoryNames = [str(i + 1) for i in range(days)]
    chart.categoryAxis.labels.fontName = FONTS["body"]
    chart.categoryAxis.labels.fontSize = 6
    chart.categoryAxis.strokeColor = RULE
    chart.valueAxis.labels.fontName = FONTS["body"]
    chart.valueAxis.labels.fontSize = 6
    chart.valueAxis.strokeColor = RULE
    chart.valueAxis.gridStrokeColor = RULE
    chart.valueAxis.visibleGrid = 1
    chart.valueAxis.valueMin = 0
    chart.valueAxis.maximumTicks = 5
    chart.valueAxis.labelTextFormat = lambda v: (f"{v/1000:.1f}k".replace(".0k", "k") if v >= 1000 else f"{v:.0f}")
    chart.categoryAxis.style = "stacked"
    chart.barWidth = 6
    chart.groupSpacing = 3
    for i, col in enumerate((GREEN_DARK, GREEN, GREEN_LIGHT)):
        chart.bars[i].fillColor = col
        chart.bars[i].strokeColor = None  # NB: never iterate chart.bars — it's an infinite factory
    d.add(chart)
    lx = 12 * mm
    for label, col in (("App Store", GREEN_DARK), ("Google Play", GREEN), ("Huawei", GREEN_LIGHT)):
        d.add(Rect(lx, 42 * mm, 3 * mm, 3 * mm, fillColor=col, strokeColor=None))
        d.add(String(lx + 4 * mm, 42.3 * mm, label, fontName=FONTS["body"], fontSize=7, fillColor=INK))
        lx += 26 * mm
    d.add(String(174 * mm, 42.3 * mm, f"Daily net ({ccy}), estimate rows", fontName=FONTS["body"], fontSize=7, fillColor=MUTED, textAnchor="end"))
    return d


def _trend_table(monthly: list[dict], month_key: str, ccy: str, st: dict) -> Table:
    by_month: dict[str, dict] = {}
    for r in monthly:
        m = by_month.setdefault(r["month"], {"appstore": 0.0, "googleplay": 0.0, "huawei": 0.0, "net": 0.0, "gross": 0.0})
        m[r["platform"]] = m.get(r["platform"], 0.0) + r["net"]
        m["net"] += r["net"]
        m["gross"] += r["gross"]
    months = sorted(k for k in by_month if k <= month_key)[-6:]
    head = ["Month", "App Store", "Google Play", "Huawei", "Net", "Gross", "MoM"]
    rows = [[Paragraph(h, ParagraphStyle("th", parent=st["cell"], textColor=PAPER, fontName=FONTS["body_b"], fontSize=8, alignment=TA_RIGHT if i else TA_LEFT)) for i, h in enumerate(head)]]
    prev = None
    for mk in months:
        m = by_month[mk]
        mom = f"{(m['net'] - prev) / prev * 100:+.1f}%" if prev else "—"
        label = datetime.strptime(mk, "%Y-%m").strftime("%b %Y")
        rows.append([
            Paragraph(label, st["cell_b" if mk == month_key else "cell"]),
            Paragraph(money(m["appstore"], ccy), st["cell_r"]),
            Paragraph(money(m["googleplay"], ccy), st["cell_r"]),
            Paragraph(money(m["huawei"], ccy), st["cell_r"]),
            Paragraph(money(m["net"], ccy), st["cell_br"]),
            Paragraph(money(m["gross"], ccy), st["cell_r"]),
            Paragraph(mom, st["cell_r"]),
        ])
        prev = m["net"] or None
    t = Table(rows, colWidths=[26 * mm, 26 * mm, 26 * mm, 24 * mm, 26 * mm, 26 * mm, 20 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN_DARK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, colors.HexColor("#F7FAF9")]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _lat(text: str) -> str:
    """Wrap Latin/currency text so it renders in the body font inside a JP paragraph (IPA Gothic has no ₱)."""
    return f'<font name="{FONTS["body"]}">{text}</font>'


def build_monthly_pdf(
    path: str,
    results: list[RevenueResult],
    year: int,
    month: int,
    daily: list[dict],
    monthly_history: list[dict],
    prev_net: Optional[float],
    ccy: str = "PHP",
    generated: Optional[datetime] = None,
) -> str:
    _register_fonts()
    st = _styles()
    generated = generated or datetime.now()
    month_label = date(year, month, 1).strftime("%B %Y")
    month_key = f"{year:04d}-{month:02d}"

    doc = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=40 * mm, bottomMargin=15 * mm,
        title=f"B-Ticket Monthly Revenue — {month_label}", author="B-Ticket Reporting Bot",
    )
    net = sum(r.net or 0 for r in results if r.ok)
    gross = sum(r.gross or 0 for r in results if r.ok)
    best = max((r for r in results if r.ok), key=lambda r: r.net or 0, default=None)

    # Japanese executive summary — first thing after the KPIs for Kento-san.
    share = f"{(best.net or 0) / net * 100:.0f}%" if best and net else "—"
    mom_txt = ""
    if prev_net:
        delta = (net - prev_net) / prev_net * 100
        mom_txt = f"前月比 {delta:+.1f}%。"
    jp = (
        f"{year}年{month}月のアプリ内課金・サブスクリプション売上は、純額 {_lat(money(net, ccy))}"
        f"（総額 {_lat(money(gross, ccy))}）となりました。{mom_txt}"
        + (f"最大のチャネルは {best.store_name}（純額の{share}）です。" if best else "")
        + " App Store は Apple の月次売上レポート（開発者収益）、Google Play は収益レポート（手数料・税・返金の確定明細）に基づく確定値です。"
          " Huawei は API に確定明細がないため、手数料率を適用した推定値です。"
    )

    story = [
        _kpi_tiles(results, prev_net, ccy, st),
        Spacer(1, 2 * mm),
        KeepTogether([
            Paragraph("エグゼクティブサマリー", st["jp_h2"]),
            Paragraph(jp, st["jp_body"]),
        ]),
        Spacer(1, 2 * mm),
        Paragraph("Reconciliation by store", st["h2"]),
        _store_table(results, ccy, st),
        Spacer(1, 3 * mm),
        Paragraph("Daily net revenue", st["h2"]),
        _daily_chart(daily, year, month, ccy),
        Spacer(1, 2 * mm),
        Paragraph("Six-month trend (net)", st["h2"]),
        _trend_table(monthly_history, month_key, ccy, st),
        Spacer(1, 1 * mm),
        Paragraph("Methodology", st["h2"]),
        Paragraph(
            "<b>App Store</b>: Apple Sales Report, MONTHLY frequency; gross = Customer Price × Units, net = Developer Proceeds × Units "
            "(after Apple commission, before withholding tax). IAP/subscription product types only (IA1, IA9, IAY, FI1 and Mac variants). "
            "<b>Google Play</b>: earnings report ledger — sum of Charge, Google fee, Tax and refund lines in merchant currency; this matches the payout. "
            "<b>Huawei</b>: AGC in-app payment export; net estimated at the configured fee rate. "
            f"All figures in {ccy}; other currencies converted at ECB reference rates (mid-month for monthly files, same-day for daily rows).",
            st["muted"],
        ),
    ]

    doc.build(story, onFirstPage=lambda c, d: _header(c, d, month_label, generated),
              onLaterPages=lambda c, d: _header(c, d, month_label, generated))
    return path
