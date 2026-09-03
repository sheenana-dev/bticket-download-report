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
    BaseDocTemplate, Frame, KeepTogether, NextPageTemplate, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
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
    "body": [os.path.join(FONT_DIR, "DejaVuSans.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "body_b": [os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
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
        # Japanese label variants (numbers keep the DejaVu styles above so ₱ renders)
        "ja_h2": ParagraphStyle("jah2", fontName=jp, fontSize=11.5, leading=16, textColor=GREEN_DARK, spaceBefore=8, spaceAfter=4),
        "ja_body": ParagraphStyle("jabody", fontName=jp, fontSize=8.5, leading=13.5, textColor=INK),
        "ja_muted": ParagraphStyle("jamuted", fontName=jp, fontSize=7.2, leading=10, textColor=MUTED),
        "ja_kpi_label": ParagraphStyle("jakl", fontName=jp, fontSize=7, leading=9, textColor=MUTED),
        "ja_kpi_delta": ParagraphStyle("jakd", fontName=jp, fontSize=7.5, leading=10, textColor=GREEN),
        "ja_cell": ParagraphStyle("jacell", fontName=jp, fontSize=8.5, leading=11, textColor=INK),
        "ja_cell_b": ParagraphStyle("jacellb", fontName=jp, fontSize=8.5, leading=11, textColor=INK),
    }


def _ls(st: dict, lang: str) -> dict:
    """Label styles for a language: JP pages use the JP font for text cells."""
    if lang == "ja":
        return {"h2": st["ja_h2"], "body": st["ja_body"], "muted": st["ja_muted"], "kpi_label": st["ja_kpi_label"],
                "kpi_delta": st["ja_kpi_delta"], "cell": st["ja_cell"], "cell_b": st["ja_cell_b"], "hdr_font": FONTS["jp"]}
    return {"h2": st["h2"], "body": st["body"], "muted": st["muted"], "kpi_label": st["kpi_label"],
            "kpi_delta": st["kpi_delta"], "cell": st["cell"], "cell_b": st["cell_b"], "hdr_font": FONTS["body_b"]}


# ----------------------------------------------------------------- i18n
# One string table per page language. Notes coming from the store parsers stay
# English (they're operational, not executive), everything else flips.
L = {
    "en": {
        "title": "B-Ticket  ·  Monthly Revenue Report",
        "subtitle": "In-app subscriptions & purchases · App Store / Google Play / Huawei",
        "generated": "Generated {ts} PHT",
        "footer": "Auto-generated by AI from store exports. Reconciled = store-reported net; Est. = fee applied by rate. Confidential.",
        "page": "Page {n} · English",
        "kpi": ("NET REVENUE", "GROSS BILLINGS", "TRANSACTIONS", "STORES REPORTING"),
        "delta": "{arrow} {pct:+.1f}% vs prior month", "no_prev": "no prior month on file",
        "take": "take-home {pct:.0f}%", "refunds_n": "{n:,} refunds · {t:,} trial starts", "all_ok": "all sources OK",
        "trials_note": " · {n} trial starts",
        "summary_h": "Executive summary",
        "recon_h": "Reconciliation by store", "daily_h": "Daily net revenue", "trend_h": "Six-month trend (net)", "method_h": "Methodology",
        "store_head": ("Store", "Gross", "Net", "Txns", "Refunds", "Basis", "Notes"),
        "reconciled": "Reconciled", "estimate": "Estimate", "unavailable": "Unavailable", "total": "Total",
        "chart_note": "Daily net ({ccy}), estimate rows",
        "trend_head": ("Month", "App Store", "Google Play", "Huawei", "Net", "Gross", "MoM"),
        "month_fmt": lambda y, m: date(y, m, 1).strftime("%b %Y"),
        "month_label": lambda y, m: date(y, m, 1).strftime("%B %Y"),
        "method": (
            "<b>App Store</b>: Apple Sales Report, MONTHLY frequency; gross = Customer Price × Units, net = Developer Proceeds × Units "
            "(after Apple commission, before withholding tax). IAP/subscription product types only (IA1, IA9, IAY, FI1 and Mac variants). "
            "<b>Google Play</b>: earnings report ledger — sum of Charge, Google fee, Tax and refund lines in merchant currency; this matches the payout. "
            "<b>Huawei</b>: AGC in-app payment export; net estimated at the configured fee rate. "
            "All figures in {ccy}; other currencies converted at ECB reference rates (mid-month for monthly files, same-day for daily rows)."
        ),
    },
    "ja": {
        "title": "B-Ticket  ·  月次売上レポート",
        "subtitle": "アプリ内サブスクリプション・課金 · App Store / Google Play / Huawei",
        "generated": "作成 {ts} PHT",
        "footer": "ストアのエクスポートデータからAIが自動生成。確定＝ストア報告の純額、推定＝手数料率を適用。社外秘。",
        "page": "{n} ページ · 日本語",
        "kpi": ("純売上", "総売上", "取引件数", "報告ストア数"),
        "delta": "{arrow} 前月比 {pct:+.1f}%", "no_prev": "前月データなし",
        "take": "手取り率 {pct:.0f}%", "refunds_n": "返金 {n:,} 件 · トライアル {t:,} 件", "all_ok": "全ソース正常",
        "trials_note": " · トライアル {n} 件",
        "summary_h": "エグゼクティブサマリー",
        "recon_h": "ストア別照合", "daily_h": "日次純売上", "trend_h": "6か月推移（純額）", "method_h": "算出方法",
        "store_head": ("ストア", "総額", "純額", "件数", "返金", "基準", "備考"),
        "reconciled": "確定", "estimate": "推定", "unavailable": "取得不可", "total": "合計",
        "chart_note": "日次純額（{ccy}）推定値",
        "trend_head": ("月", "App Store", "Google Play", "Huawei", "純額", "総額", "前月比"),
        "month_fmt": lambda y, m: f"{y}年{m}月",
        "month_label": lambda y, m: f"{y}年{m}月",
        "method": (
            "<b>App Store</b>：Apple 売上レポート（月次）。総額＝顧客価格×数量、純額＝開発者収益×数量（Apple 手数料控除後・源泉税控除前）。"
            "アプリ内課金・サブスクリプション種別（IA1, IA9, IAY, FI1 および Mac 版）のみ集計。"
            "<b>Google Play</b>：収益レポートの明細（請求・Google 手数料・税・返金）を加盟店通貨で合計。支払額と一致します。"
            "<b>Huawei</b>：AGC アプリ内課金エクスポート。純額は設定した手数料率による推定値。"
            "すべて {ccy} 建て。他通貨は ECB 参照レート（月次は月央、日次は当日）で換算。"
        ),
    },
}


def _header(canvas, doc, lang: str, year: int, month: int, generated: datetime) -> None:
    t = L[lang]
    jp = lang == "ja"
    head_font = FONTS["jp"] if jp else FONTS["head"]
    body_font = FONTS["jp"] if jp else FONTS["body"]
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(GREEN_DARK)
    canvas.rect(0, h - 34 * mm, w, 34 * mm, stroke=0, fill=1)
    canvas.setFillColor(YELLOW)
    canvas.rect(0, h - 34 * mm, w, 1.5 * mm, stroke=0, fill=1)
    canvas.setFillColor(PAPER)
    canvas.setFont(head_font, 19)
    canvas.drawString(18 * mm, h - 17 * mm, t["title"])
    canvas.setFont(body_font, 9)
    canvas.setFillColor(colors.HexColor("#D8EBE3"))
    canvas.drawString(18 * mm, h - 24 * mm, f"{t['month_label'](year, month)}   ·   {t['subtitle']}")
    canvas.setFont(body_font, 8)
    canvas.drawRightString(w - 18 * mm, h - 15 * mm, t["generated"].format(ts=f"{generated:%Y-%m-%d %H:%M}"))
    canvas.setFillColor(MUTED)
    canvas.setFont(body_font, 7)
    canvas.drawString(18 * mm, 10 * mm, t["footer"])
    canvas.drawRightString(w - 18 * mm, 10 * mm, t["page"].format(n=doc.page))
    canvas.restoreState()


def _kpi_tiles(results: list[RevenueResult], prev_net: Optional[float], ccy: str, st: dict, lang: str = "en") -> Table:
    t, ls = L[lang], _ls(st, lang)
    net = sum(r.net or 0 for r in results if r.ok)
    gross = sum(r.gross or 0 for r in results if r.ok)
    txns = sum(r.transactions or 0 for r in results if r.ok)
    refunds = sum(r.refunds or 0 for r in results if r.ok)
    trials = sum(r.trials or 0 for r in results if r.ok)
    take = (net / gross * 100) if gross else 0.0
    if prev_net:
        delta = (net - prev_net) / prev_net * 100
        delta_txt = t["delta"].format(arrow=_lat("▲" if delta >= 0 else "▼"), pct=delta)
    else:
        delta_txt = t["no_prev"]

    def tile(label, value, sub):
        return [Paragraph(label, ls["kpi_label"]), Paragraph(value, st["kpi_value"]), Paragraph(sub, ls["kpi_delta"])]

    k = t["kpi"]
    data = [[
        tile(k[0], money(net, ccy), delta_txt),
        tile(k[1], money(gross, ccy), t["take"].format(pct=take)),
        tile(k[2], f"{txns:,}", t["refunds_n"].format(n=refunds, t=trials)),
        tile(k[3], f"{sum(1 for r in results if r.ok)}/{len(results)}",
             ", ".join(r.store_name for r in results if not r.ok) or t["all_ok"]),
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


def _native_note(native: dict) -> str:
    """" · native PHP 396, USD 1.61" — skip zero lines, keep cents for small amounts."""
    parts = []
    for k, v in native.items():
        if abs(v) < 0.005:
            continue
        parts.append(f"{k} {v:,.2f}" if abs(v) < 100 else f"{k} {v:,.0f}")
    return (" · native " + ", ".join(parts)) if parts else ""


def _store_table(results: list[RevenueResult], ccy: str, st: dict, lang: str = "en") -> Table:
    t, ls = L[lang], _ls(st, lang)
    head = list(t["store_head"])
    rows = [[Paragraph(h, ParagraphStyle("hdr", parent=st["cell_r" if i in (1, 2, 3, 4) else "cell"],
                                         textColor=PAPER, fontName=ls["hdr_font"], fontSize=7))
             for i, h in enumerate(head)]]
    for r in results:
        if r.ok:
            rows.append([
                Paragraph(r.store_name, st["cell_b"]),
                Paragraph(money(r.gross, ccy), st["cell_r"]),
                Paragraph(money(r.net, ccy), st["cell_br"]),
                Paragraph(f"{r.transactions or 0:,}", st["cell_r"]),
                Paragraph(f"{r.refunds or 0:,}", st["cell_r"]),
                Paragraph(t["reconciled"] if r.basis == "reconciled" else t["estimate"], ls["cell"]),
                Paragraph((r.note or "") + _native_note(r.native_gross)
                          + (t["trials_note"].format(n=r.trials) if r.trials else ""), st["muted"] if lang == "en" else ls["muted"]),
            ])
        else:
            rows.append([
                Paragraph(r.store_name, st["cell_b"]),
                Paragraph("—", st["cell_r"]), Paragraph("—", st["cell_r"]),
                Paragraph("—", st["cell_r"]), Paragraph("—", st["cell_r"]),
                Paragraph(t["unavailable"], ls["cell"]),
                Paragraph(r.error_message or r.note or "", st["muted"]),
            ])
    net = sum(r.net or 0 for r in results if r.ok)
    gross = sum(r.gross or 0 for r in results if r.ok)
    rows.append([
        Paragraph(t["total"], ls["cell_b"]),
        Paragraph(money(gross, ccy), st["cell_br"]),
        Paragraph(money(net, ccy), st["cell_br"]),
        Paragraph(f"{sum(r.transactions or 0 for r in results if r.ok):,}", st["cell_br"]),
        Paragraph(f"{sum(r.refunds or 0 for r in results if r.ok):,}", st["cell_br"]),
        "", "",
    ])
    tbl = Table(rows, colWidths=[27 * mm, 22 * mm, 22 * mm, 13 * mm, 18 * mm, 22 * mm, 50 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), PAPER),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, GREEN_DARK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [PAPER, colors.HexColor("#F7FAF9")]),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, GREEN_DARK),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF3EE")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return tbl


def _daily_chart(daily: list[dict], year: int, month: int, ccy: str, lang: str = "en") -> Drawing:
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
    note_font = FONTS["jp"] if lang == "ja" else FONTS["body"]
    d.add(String(174 * mm, 42.3 * mm, L[lang]["chart_note"].format(ccy=ccy), fontName=note_font, fontSize=7, fillColor=MUTED, textAnchor="end"))
    return d


def _trend_table(monthly: list[dict], month_key: str, ccy: str, st: dict, lang: str = "en") -> Table:
    t, ls = L[lang], _ls(st, lang)
    by_month: dict[str, dict] = {}
    for r in monthly:
        m = by_month.setdefault(r["month"], {"appstore": 0.0, "googleplay": 0.0, "huawei": 0.0, "net": 0.0, "gross": 0.0})
        m[r["platform"]] = m.get(r["platform"], 0.0) + r["net"]
        m["net"] += r["net"]
        m["gross"] += r["gross"]
    months = sorted(k for k in by_month if k <= month_key)[-6:]
    head = list(t["trend_head"])
    rows = [[Paragraph(h, ParagraphStyle("th", parent=st["cell"], textColor=PAPER, fontName=ls["hdr_font"], fontSize=8, alignment=TA_RIGHT if i else TA_LEFT)) for i, h in enumerate(head)]]
    prev = None
    for mk in months:
        m = by_month[mk]
        mom = f"{(m['net'] - prev) / prev * 100:+.1f}%" if prev else "—"
        yy, mm_ = (int(x) for x in mk.split("-"))
        label = t["month_fmt"](yy, mm_)
        rows.append([
            Paragraph(label, ls["cell_b" if mk == month_key else "cell"]),
            Paragraph(money(m["appstore"], ccy), st["cell_r"]),
            Paragraph(money(m["googleplay"], ccy), st["cell_r"]),
            Paragraph(money(m["huawei"], ccy), st["cell_r"]),
            Paragraph(money(m["net"], ccy), st["cell_br"]),
            Paragraph(money(m["gross"], ccy), st["cell_r"]),
            Paragraph(mom, st["cell_r"]),
        ])
        prev = m["net"] or None
    tbl = Table(rows, colWidths=[26 * mm, 26 * mm, 26 * mm, 24 * mm, 26 * mm, 26 * mm, 20 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN_DARK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, colors.HexColor("#F7FAF9")]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tbl


def _lat(text: str) -> str:
    """Wrap Latin/currency text so it renders in the body font inside a JP paragraph (IPA Gothic has no ₱)."""
    return f'<font name="{FONTS["body"]}">{text}</font>'


def _summary(lang: str, results, year, month, net, gross, prev_net, ccy) -> str:
    best = max((r for r in results if r.ok), key=lambda r: r.net or 0, default=None)
    share = (best.net or 0) / net * 100 if best and net else None
    if lang == "ja":
        mom = ""
        if prev_net:
            mom = f"前月比 {(net - prev_net) / prev_net * 100:+.1f}%。"
        return (
            f"{year}年{month}月のアプリ内課金・サブスクリプション売上は、純額 {_lat(money(net, ccy))}"
            f"（総額 {_lat(money(gross, ccy))}）となりました。{mom}"
            + (f"最大のチャネルは {best.store_name}（純額の{share:.0f}%）です。" if best else "")
            + " App Store は Apple の月次売上レポート（開発者収益）、Google Play は収益レポート（手数料・税・返金の確定明細）に基づく確定値です。"
              " Huawei は API に確定明細がないため、手数料率を適用した推定値です。"
        )
    mom = ""
    if prev_net:
        mom = f" That is {(net - prev_net) / prev_net * 100:+.1f}% versus the prior month."
    lead = f"In-app subscription and purchase revenue for {date(year, month, 1):%B %Y} was {money(net, ccy)} net ({money(gross, ccy)} gross).{mom}"
    chan = f" The largest channel was {best.store_name} at {share:.0f}% of net." if best else ""
    return (lead + chan +
            " App Store and Google Play figures are reconciled (Apple monthly sales report; Google earnings ledger). "
            "Huawei is an estimate — its API exposes no settlement ledger, so the configured fee rate is applied.")


def _page(lang: str, results, year, month, daily, monthly_history, prev_net, ccy, st) -> list:
    t, ls = L[lang], _ls(st, lang)
    month_key = f"{year:04d}-{month:02d}"
    net = sum(r.net or 0 for r in results if r.ok)
    gross = sum(r.gross or 0 for r in results if r.ok)
    return [
        _kpi_tiles(results, prev_net, ccy, st, lang),
        Spacer(1, 2 * mm),
        KeepTogether([
            Paragraph(t["summary_h"], ls["h2"]),
            Paragraph(_summary(lang, results, year, month, net, gross, prev_net, ccy), ls["body"]),
        ]),
        Spacer(1, 2 * mm),
        Paragraph(t["recon_h"], ls["h2"]),
        _store_table(results, ccy, st, lang),
        Spacer(1, 3 * mm),
        Paragraph(t["daily_h"], ls["h2"]),
        _daily_chart(daily, year, month, ccy, lang),
        Spacer(1, 2 * mm),
        Paragraph(t["trend_h"], ls["h2"]),
        _trend_table(monthly_history, month_key, ccy, st, lang),
        Spacer(1, 1 * mm),
        Paragraph(t["method_h"], ls["h2"]),
        Paragraph(t["method"].format(ccy=ccy), ls["muted"]),
    ]


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
    languages: tuple = ("en", "ja"),
) -> str:
    """One PDF, one page per language (English first, then Japanese)."""
    _register_fonts()
    st = _styles()
    generated = generated or datetime.now()

    frame = Frame(18 * mm, 15 * mm, A4[0] - 36 * mm, A4[1] - 55 * mm, id="body",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    templates = [
        PageTemplate(id=lang, frames=[frame],
                     onPage=(lambda lang_: lambda c, d: _header(c, d, lang_, year, month, generated))(lang))
        for lang in languages
    ]
    doc = BaseDocTemplate(
        path, pagesize=A4, pageTemplates=templates,
        title=f"B-Ticket Monthly Revenue — {L['en']['month_label'](year, month)}", author="B-Ticket Reporting Bot",
    )

    story: list = []
    for i, lang in enumerate(languages):
        if i:
            story += [NextPageTemplate(lang), PageBreak()]
        story += _page(lang, results, year, month, daily, monthly_history, prev_net, ccy, st)
    doc.build(story)
    return path
