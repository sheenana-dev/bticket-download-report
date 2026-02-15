"""B-Ticket Download Dashboard.

Streamlit app for visualizing daily download metrics
from App Store and Google Play, styled with B-ticket brand identity.
"""

import base64
import os
from io import StringIO

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _img_to_base64(filename: str) -> str:
    """Read an image from assets/ and return a base64-encoded data URI."""
    path = os.path.join(ASSETS_DIR, filename)
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    ext = filename.rsplit(".", 1)[-1].lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "svg": "image/svg+xml"}.get(ext, "image/png")
    return f"data:{mime};base64,{data}"

DEFAULT_CSV_URL = (
    "https://raw.githubusercontent.com/sheenana-dev/"
    "bticket-download-report/main/data/downloads.csv"
)
LOCAL_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "downloads.csv",
)

PLATFORM_LABELS = {"appstore": "App Store", "googleplay": "Google Play"}

# ── B-Ticket Brand Colors (Brand Kit 2025) ──
# Primary
BT_DEEP_SEA_GREEN = "#205C50"
BT_DARK_PASTEL_GREEN = "#56A66F"
BT_PALE_TEAL = "#84BEA1"
BT_DARK_JUNGLE = "#221F1F"
# Secondary
BT_CORAL_RED = "#EE4036"
BT_PALE_ORANGE = "#F9A250"
BT_DANDELION = "#F1E048"
BT_CRYSTAL_BLUE = "#50C9EF"
BT_COTTON_CANDY = "#FFBCD1"

PLATFORM_COLORS = {
    "App Store": BT_DEEP_SEA_GREEN,
    "Google Play": BT_DARK_PASTEL_GREEN,
    "Combined": BT_PALE_ORANGE,
}

CHART_LAYOUT = dict(
    font_family="Poppins, Montserrat, sans-serif",
    font_color=BT_DARK_JUNGLE,
    title_font_color=BT_DEEP_SEA_GREEN,
    title_font_size=15,
    title_font_weight=600,
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    legend=dict(
        bgcolor="rgba(255,255,255,0.85)",
        bordercolor=BT_PALE_TEAL,
        borderwidth=1,
        font_size=11,
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
    ),
    margin=dict(l=40, r=20, t=60, b=40),
)

BRAND_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&family=Montserrat:wght@300;400;500;600;700&display=swap');

/* ── Global ── */
html, body, [class*="st-"] {
    font-family: 'Poppins', 'Montserrat', sans-serif;
}
h1, h2, h3, h4, h5, h6 {
    font-family: 'Poppins', 'Montserrat', sans-serif !important;
    color: #205C50 !important;
    font-weight: 600 !important;
}

/* ── Main background ── */
.stApp {
    background: linear-gradient(170deg, #f0f8f4 0%, #ffffff 40%, #fef9f5 100%);
}

/* ── Hero card styling ── */
.hero-card {
    background: white;
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 2px 12px rgba(32, 92, 80, 0.07);
    border-left: 4px solid #84BEA1;
    margin-bottom: 8px;
}
.hero-card.appstore { border-left-color: #205C50; }
.hero-card.googleplay { border-left-color: #56A66F; }
.hero-card.combined { border-left-color: #F9A250; }

.hero-value {
    font-size: 2.6rem;
    font-weight: 700;
    color: #205C50;
    line-height: 1.1;
    font-family: 'Poppins', sans-serif;
}
.hero-label {
    font-size: 0.8rem;
    color: #221F1F;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 500;
    margin-bottom: 4px;
}
.hero-sub {
    font-size: 0.85rem;
    color: #56A66F;
    margin-top: 6px;
    font-weight: 500;
}
.hero-delta {
    font-size: 0.78rem;
    font-weight: 500;
    margin-top: 2px;
}
.hero-delta.up { color: #56A66F; }
.hero-delta.down { color: #EE4036; }
.hero-delta.flat { color: #999; }

/* ── Stat pills row ── */
.stat-row {
    display: flex;
    gap: 12px;
    margin: 16px 0 8px 0;
    flex-wrap: wrap;
}
.stat-pill {
    background: white;
    border: 1px solid #84BEA1;
    border-radius: 24px;
    padding: 10px 20px;
    text-align: center;
    flex: 1;
    min-width: 120px;
    box-shadow: 0 1px 4px rgba(32, 92, 80, 0.05);
}
.stat-pill-label {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #666;
    font-weight: 500;
}
.stat-pill-value {
    font-size: 1.15rem;
    font-weight: 600;
    color: #205C50;
}

/* ── Metric overrides ── */
[data-testid="stMetricValue"] {
    color: #205C50 !important;
    font-weight: 700 !important;
    font-size: 2.2rem !important;
}
[data-testid="stMetricLabel"] {
    color: #221F1F !important;
    font-weight: 500 !important;
    font-size: 0.82rem !important;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
[data-testid="stMetricDelta"] { font-weight: 500 !important; }
[data-testid="stMetric"] {
    background: white;
    border: 1px solid #84BEA1;
    border-radius: 12px;
    padding: 16px 20px !important;
    box-shadow: 0 2px 8px rgba(32, 92, 80, 0.06);
}
[data-testid="stMetric"]:hover {
    box-shadow: 0 4px 16px rgba(32, 92, 80, 0.12);
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #205C50 0%, #184a40 100%) !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span {
    color: white !important;
}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
    color: #b8dcc8 !important;
}
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] select {
    color: #221F1F !important;
    border-radius: 8px !important;
}
section[data-testid="stSidebar"] [data-baseweb="select"] {
    border-radius: 8px !important;
}

/* ── Dividers ── */
hr {
    border: none !important;
    height: 2px !important;
    background: linear-gradient(90deg, #84BEA1, #205C50, #84BEA1) !important;
    opacity: 0.3;
    margin: 1.5rem 0 !important;
}

/* ── Chart containers ── */
[data-testid="stPlotlyChart"] {
    background: white;
    border-radius: 14px;
    border: 1px solid rgba(132, 190, 161, 0.25);
    padding: 8px;
    box-shadow: 0 2px 10px rgba(32, 92, 80, 0.05);
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: rgba(132, 190, 161, 0.1);
    border-radius: 12px;
    padding: 4px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 10px;
    font-family: 'Poppins', sans-serif;
    font-weight: 500;
    font-size: 0.85rem;
    color: #205C50;
    padding: 8px 20px;
}
.stTabs [aria-selected="true"] {
    background: #205C50 !important;
    color: white !important;
    border-radius: 10px;
}
.stTabs [data-baseweb="tab-highlight"] {
    display: none;
}
.stTabs [data-baseweb="tab-border"] {
    display: none;
}

/* ── Captions ── */
[data-testid="stCaptionContainer"] {
    color: #56A66F !important;
    font-size: 0.78rem !important;
}

/* ── Buttons ── */
.stButton > button {
    background-color: #205C50 !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'Poppins', sans-serif !important;
    font-weight: 500 !important;
}
.stButton > button:hover {
    background-color: #56A66F !important;
}

/* ── Date input ── */
[data-testid="stDateInput"] input {
    border-radius: 8px !important;
    border-color: #84BEA1 !important;
}

/* ── Columns gap ── */
[data-testid="stHorizontalBlock"] {
    gap: 1rem;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    background: white;
    border: 1px solid rgba(132, 190, 161, 0.3);
    border-radius: 12px;
    box-shadow: 0 1px 6px rgba(32, 92, 80, 0.04);
}
</style>
"""


@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    """Load download data from GitHub raw URL or local file."""
    csv_url = os.environ.get("GITHUB_CSV_URL", DEFAULT_CSV_URL)
    df = None

    if csv_url:
        try:
            resp = requests.get(csv_url, timeout=10)
            resp.raise_for_status()
            df = pd.read_csv(StringIO(resp.text))
        except Exception:
            pass

    if df is None and os.path.exists(LOCAL_CSV_PATH):
        df = pd.read_csv(LOCAL_CSV_PATH)

    if df is None or df.empty:
        st.error("No data available. Check your CSV source configuration.")
        st.stop()

    df["report_date"] = pd.to_datetime(df["report_date"])
    df["date"] = pd.to_datetime(df["date"])
    df["platform_label"] = df["platform"].map(PLATFORM_LABELS)
    return df


def _apply_chart_style(fig: go.Figure) -> go.Figure:
    """Apply consistent brand styling to a Plotly figure."""
    fig.update_layout(**CHART_LAYOUT)
    fig.update_xaxes(
        gridcolor="rgba(132,190,161,0.15)",
        linecolor=BT_PALE_TEAL,
        title_font_color=BT_DEEP_SEA_GREEN,
    )
    fig.update_yaxes(
        gridcolor="rgba(132,190,161,0.15)",
        linecolor=BT_PALE_TEAL,
        title_font_color=BT_DEEP_SEA_GREEN,
    )
    return fig


def _delta_html(current: int, previous: int) -> str:
    """Return styled delta HTML comparing current vs previous."""
    if previous == 0:
        return '<span class="hero-delta flat">--</span>'
    diff = current - previous
    sign = "+" if diff >= 0 else ""
    cls = "up" if diff >= 0 else "down"
    arrow = "\u25b2" if diff > 0 else "\u25bc" if diff < 0 else ""
    return f'<span class="hero-delta {cls}">{arrow} {sign}{diff:,} vs yesterday</span>'


def render_hero_section(df: pd.DataFrame) -> None:
    """Render consolidated hero metrics — today's snapshot."""
    latest_date = df["report_date"].max()
    today_df = df[df["report_date"] == latest_date]
    yesterday = latest_date - pd.Timedelta(days=1)
    yesterday_df = df[df["report_date"] == yesterday]

    st.markdown(
        f"<p style='margin:0 0 16px 0; color:#56A66F; font-size:0.9rem;'>"
        f"\U0001f4c5 Latest data: <strong>{latest_date.strftime('%B %d, %Y')}</strong></p>",
        unsafe_allow_html=True,
    )

    platforms = [
        ("\U0001f34e", "App Store", "appstore", "appstore"),
        ("\U0001f916", "Google Play", "googleplay", "googleplay"),
    ]

    total_today = 0
    total_yesterday = 0
    grand_total = 0

    cols = st.columns(3)

    for i, (icon, label, key, css_cls) in enumerate(platforms):
        today_row = today_df[today_df["platform"] == key]
        yest_row = yesterday_df[yesterday_df["platform"] == key]

        today_dl = int(today_row["daily_downloads"].sum()) if not today_row.empty else 0
        today_cum = int(today_row["cumulative_total"].iloc[-1]) if not today_row.empty else 0
        yest_dl = int(yest_row["daily_downloads"].sum()) if not yest_row.empty else 0

        total_today += today_dl
        total_yesterday += yest_dl
        grand_total += today_cum

        delta = _delta_html(today_dl, yest_dl)

        with cols[i]:
            st.markdown(
                f'<div class="hero-card {css_cls}">'
                f'  <div class="hero-label">{icon} {label}</div>'
                f'  <div class="hero-value">{today_dl:,}</div>'
                f'  {delta}'
                f'  <div class="hero-sub">Total: {today_cum:,}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # Combined card
    combined_delta = _delta_html(total_today, total_yesterday)
    with cols[2]:
        st.markdown(
            f'<div class="hero-card combined">'
            f'  <div class="hero-label">\U0001f4e6 Combined</div>'
            f'  <div class="hero-value">{total_today:,}</div>'
            f'  {combined_delta}'
            f'  <div class="hero-sub">Grand Total: {grand_total:,}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Stat pills — secondary insights in compact form
    daily_combined = df.groupby("report_date")["daily_downloads"].sum().sort_index()
    avg_7 = daily_combined.tail(7).mean()
    avg_30 = daily_combined.tail(30).mean()
    pct_vs_avg = ((total_today / avg_7) - 1) * 100 if avg_7 > 0 else 0
    best_day = int(daily_combined.max())

    pct_color = BT_DARK_PASTEL_GREEN if pct_vs_avg >= 0 else BT_CORAL_RED
    pct_sign = "+" if pct_vs_avg >= 0 else ""

    st.markdown(
        f'<div class="stat-row">'
        f'  <div class="stat-pill">'
        f'    <div class="stat-pill-label">7-Day Avg</div>'
        f'    <div class="stat-pill-value">{avg_7:,.1f}</div>'
        f'  </div>'
        f'  <div class="stat-pill">'
        f'    <div class="stat-pill-label">30-Day Avg</div>'
        f'    <div class="stat-pill-value">{avg_30:,.1f}</div>'
        f'  </div>'
        f'  <div class="stat-pill">'
        f'    <div class="stat-pill-label">vs 7-Day Avg</div>'
        f'    <div class="stat-pill-value" style="color:{pct_color}">{pct_sign}{pct_vs_avg:.0f}%</div>'
        f'  </div>'
        f'  <div class="stat-pill">'
        f'    <div class="stat-pill-label">Best Day</div>'
        f'    <div class="stat-pill-value">{best_day:,}</div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_daily_chart(df: pd.DataFrame) -> None:
    """Daily downloads stacked bar + combined trend line."""
    daily = df.groupby(["report_date", "platform_label"])["daily_downloads"].sum().reset_index()
    combined = df.groupby("report_date")["daily_downloads"].sum().reset_index()

    fig = go.Figure()

    for platform in ["App Store", "Google Play"]:
        pdf = daily[daily["platform_label"] == platform]
        fig.add_trace(go.Bar(
            x=pdf["report_date"],
            y=pdf["daily_downloads"],
            name=platform,
            marker_color=PLATFORM_COLORS.get(platform),
            marker_line_width=0,
            hovertemplate="%{y:,} downloads<extra>" + platform + "</extra>",
        ))

    fig.add_trace(go.Scatter(
        x=combined["report_date"],
        y=combined["daily_downloads"],
        name="Combined",
        mode="lines+markers",
        line=dict(color=BT_PALE_ORANGE, width=2.5),
        marker=dict(size=4, color=BT_PALE_ORANGE),
        hovertemplate="%{y:,} total<extra>Combined</extra>",
    ))

    fig.update_layout(
        title="Daily Downloads",
        barmode="stack",
        hovermode="x unified",
        xaxis_title="",
        yaxis_title="Downloads",
        height=420,
    )
    _apply_chart_style(fig)
    st.plotly_chart(fig, use_container_width=True, key="chart_daily")


def render_growth_chart(df: pd.DataFrame) -> None:
    """Total growth area chart by platform."""
    cum = df.sort_values("report_date")

    fig = go.Figure()
    for platform in ["App Store", "Google Play"]:
        pdf = cum[cum["platform_label"] == platform]
        fig.add_trace(go.Scatter(
            x=pdf["report_date"],
            y=pdf["cumulative_total"],
            name=platform,
            mode="lines",
            fill="tozeroy",
            line=dict(color=PLATFORM_COLORS.get(platform), width=2),
            fillcolor=PLATFORM_COLORS.get(platform).replace(")", ",0.15)").replace("rgb", "rgba") if "rgb" in PLATFORM_COLORS.get(platform, "") else None,
            hovertemplate="%{y:,}<extra>" + platform + "</extra>",
        ))

    fig.update_layout(
        title="Total Growth",
        hovermode="x unified",
        xaxis_title="",
        yaxis_title="Total Downloads",
        height=420,
    )
    _apply_chart_style(fig)
    # Manual fill colors since hex doesn't support rgba
    fig.data[0].fillcolor = "rgba(32,92,80,0.15)"
    fig.data[1].fillcolor = "rgba(86,166,111,0.15)"
    st.plotly_chart(fig, use_container_width=True, key="chart_growth")


def render_trend_chart(df: pd.DataFrame) -> None:
    """7-day moving average trend lines."""
    daily = df.groupby(["report_date", "platform_label"])["daily_downloads"].sum().reset_index()

    fig = go.Figure()
    for platform in daily["platform_label"].unique():
        pdf = daily[daily["platform_label"] == platform].sort_values("report_date")
        pdf["ma7"] = pdf["daily_downloads"].rolling(7, min_periods=1).mean()
        fig.add_trace(go.Scatter(
            x=pdf["report_date"],
            y=pdf["ma7"],
            mode="lines",
            name=platform,
            line=dict(color=PLATFORM_COLORS.get(platform), width=2.5),
            hovertemplate="%{y:,.1f}<extra>" + platform + "</extra>",
        ))

    combined = daily.groupby("report_date")["daily_downloads"].sum().reset_index().sort_values("report_date")
    combined["ma7"] = combined["daily_downloads"].rolling(7, min_periods=1).mean()
    fig.add_trace(go.Scatter(
        x=combined["report_date"],
        y=combined["ma7"],
        mode="lines",
        name="Combined",
        line=dict(dash="dash", color=BT_PALE_ORANGE, width=2.5),
        hovertemplate="%{y:,.1f}<extra>Combined</extra>",
    ))

    fig.update_layout(
        title="7-Day Moving Average",
        hovermode="x unified",
        xaxis_title="",
        yaxis_title="Avg Downloads",
        height=420,
    )
    _apply_chart_style(fig)
    st.plotly_chart(fig, use_container_width=True, key="chart_trend")


def render_platform_split(df: pd.DataFrame) -> None:
    """Platform split donut + breakdown bar."""
    totals = df.groupby("platform_label")["daily_downloads"].sum().reset_index()
    grand = totals["daily_downloads"].sum()

    fig = go.Figure()
    fig.add_trace(go.Pie(
        labels=totals["platform_label"],
        values=totals["daily_downloads"],
        hole=0.5,
        marker=dict(
            colors=[PLATFORM_COLORS.get(p, BT_PALE_TEAL) for p in totals["platform_label"]],
            line=dict(color="white", width=3),
        ),
        textinfo="percent+label",
        textfont=dict(size=12, family="Poppins"),
        hovertemplate="%{label}: %{value:,} (%{percent})<extra></extra>",
    ))

    fig.update_layout(
        title="Platform Split",
        height=420,
        annotations=[dict(
            text=f"<b>{grand:,}</b><br>total",
            x=0.5, y=0.5,
            font=dict(size=16, color=BT_DEEP_SEA_GREEN, family="Poppins"),
            showarrow=False,
        )],
    )
    _apply_chart_style(fig)
    st.plotly_chart(fig, use_container_width=True, key="chart_split")


def render_data_table(df: pd.DataFrame) -> None:
    """Styled data table with download history."""
    display_df = df[["report_date", "platform_label", "daily_downloads", "cumulative_total"]].copy()
    display_df.columns = ["Date", "Platform", "Daily", "Total"]
    display_df["Date"] = display_df["Date"].dt.strftime("%Y-%m-%d")
    display_df = display_df.sort_values("Date", ascending=False).reset_index(drop=True)
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        key="downloads_table",
    )


def main() -> None:
    """Entry point for the Streamlit dashboard."""
    st.set_page_config(
        page_title="B-ticket Downloads",
        page_icon="\U0001f989",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(BRAND_CSS, unsafe_allow_html=True)

    df = load_data()

    # ── Preload brand images ──
    logo_b64 = _img_to_base64("logo.png")
    bibo_b64 = _img_to_base64("bibo.png")
    bibi_b64 = _img_to_base64("bibi.png")

    # ── Sidebar ──
    with st.sidebar:
        # Logo
        if logo_b64:
            st.markdown(
                f"<div style='text-align:center; padding:16px 0 4px 0;'>"
                f"<img src='{logo_b64}' style='width:180px; filter:brightness(0) invert(1);' />"
                f"</div>",
                unsafe_allow_html=True,
            )
        st.markdown(
            "<p style='text-align:center; font-size:0.75rem; margin:2px 0 0 0; "
            "color:#FFBCD1 !important; font-style:italic;'>"
            "Your Coupon Bestfriend!</p>",
            unsafe_allow_html=True,
        )
        # Bibo mascot in sidebar
        if bibo_b64:
            st.markdown(
                f"<div style='text-align:center; padding:8px 0;'>"
                f"<img src='{bibo_b64}' style='width:100px; opacity:0.9;' />"
                f"</div>",
                unsafe_allow_html=True,
            )
        st.divider()

        st.markdown(
            "<p style='font-size:0.8rem; font-weight:600; "
            "letter-spacing:0.05em; text-transform:uppercase;'>"
            "\U0001f50d Filters</p>",
            unsafe_allow_html=True,
        )

        min_date = df["report_date"].min().date()
        max_date = df["report_date"].max().date()
        date_range = st.date_input(
            "Date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            key=f"date_range_{min_date}_{max_date}",
        )

        platform_options = ["All", "App Store", "Google Play"]
        platform_filter = st.selectbox("Platform", platform_options)

        st.divider()

        # Quick sidebar stats
        latest = df[df["report_date"] == df["report_date"].max()]
        sidebar_total = int(latest["cumulative_total"].sum()) if not latest.empty else 0
        st.markdown(
            f"<div style='text-align:center; padding:8px 0;'>"
            f"<p style='font-size:0.7rem; text-transform:uppercase; letter-spacing:0.05em; "
            f"margin-bottom:4px;'>Grand Total</p>"
            f"<p style='font-size:1.8rem; font-weight:700; color:#FFBCD1 !important; "
            f"margin:0;'>{sidebar_total:,}</p>"
            f"<p style='font-size:0.7rem; margin-top:4px;'>"
            f"{min_date} \u2192 {max_date}</p>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── Header ──
    hdr_left, hdr_right = st.columns([5, 1])
    with hdr_left:
        if logo_b64:
            st.markdown(
                f"<div style='display:flex; align-items:center; gap:12px;'>"
                f"<img src='{logo_b64}' style='height:48px;' />"
                f"<span style='font-size:1.4rem; font-weight:600; color:#205C50;'>"
                f"Download Dashboard</span></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<h1 style='margin-bottom: 0.1rem; font-size: 1.8rem;'>"
                "B-ticket Download Dashboard</h1>",
                unsafe_allow_html=True,
            )
    with hdr_right:
        if bibi_b64:
            st.markdown(
                f"<div style='text-align:right;'>"
                f"<img src='{bibi_b64}' style='height:60px;' /></div>",
                unsafe_allow_html=True,
            )

    # ── Hero section (unfiltered — always shows latest day) ──
    render_hero_section(df)

    st.divider()

    # ── Apply sidebar filters for charts ──
    filtered = df.copy()
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
        filtered = filtered[
            (filtered["report_date"] >= start) & (filtered["report_date"] <= end)
        ]

    if platform_filter != "All":
        filtered = filtered[filtered["platform_label"] == platform_filter]

    if filtered.empty:
        st.warning("No data for the selected filters.")
        return

    # ── Charts in tabs ──
    tab_daily, tab_growth, tab_trend, tab_split = st.tabs(
        ["\U0001f4ca Daily", "\U0001f4c8 Growth", "\U0001f4c9 Trend", "\U0001f967 Split"]
    )

    with tab_daily:
        render_daily_chart(filtered)
    with tab_growth:
        render_growth_chart(filtered)
    with tab_trend:
        render_trend_chart(filtered)
    with tab_split:
        render_platform_split(filtered)

    # ── Data Table ──
    st.divider()
    show_data = st.checkbox("Show Raw Data", value=False, key="toggle_raw_data")
    if show_data:
        render_data_table(filtered)

    # ── Footer ──
    st.divider()
    footer_img = ""
    if bibo_b64 and bibi_b64:
        footer_img = (
            f"<img src='{bibo_b64}' style='height:45px; vertical-align:middle;' />"
            f"&nbsp;&nbsp;"
            f"<img src='{bibi_b64}' style='height:45px; vertical-align:middle;' />"
        )
    st.markdown(
        f"<div style='text-align:center; padding:8px 0;'>"
        f"{footer_img}<br>"
        f"<span style='color:#84BEA1; font-size:0.78rem;'>"
        f"B-ticket &middot; Your Coupon Bestfriend! &middot; "
        f"Auto-generated dashboard</span></div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
