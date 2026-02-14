"""B-Ticket Download Dashboard.

Streamlit app for visualizing daily download metrics
from App Store and Google Play.
"""

import os
from datetime import timedelta
from io import StringIO

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

DEFAULT_CSV_URL = (
    "https://raw.githubusercontent.com/sheenana-dev/"
    "bticket-download-report/main/data/downloads.csv"
)
LOCAL_CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "downloads.csv")

PLATFORM_LABELS = {"appstore": "App Store", "googleplay": "Google Play"}

# B-Ticket brand colors
BT_DEEP_SEA_GREEN = "#205C50"
BT_DARK_PASTEL_GREEN = "#56A66F"
BT_PALE_TEAL = "#84BEA1"
BT_DARK_JUNGLE = "#221F1F"
BT_CORAL_RED = "#EE4036"
BT_PALE_ORANGE = "#F9A250"
BT_DANDELION = "#F1E048"
BT_CRYSTAL_BLUE = "#50C9EF"
BT_COTTON_CANDY = "#FFBCD1"

# Chart color mapping
PLATFORM_COLORS = {
    "App Store": BT_DEEP_SEA_GREEN,
    "Google Play": BT_DARK_PASTEL_GREEN,
    "Combined": BT_PALE_ORANGE,
}

BRAND_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');

html, body, [class*="st-"] {
    font-family: 'Poppins', sans-serif;
}

h1, h2, h3, h4, h5, h6 {
    font-family: 'Poppins', sans-serif !important;
    color: #205C50 !important;
}

/* Metric cards */
[data-testid="stMetricValue"] {
    color: #205C50 !important;
    font-weight: 600 !important;
}

[data-testid="stMetricLabel"] {
    color: #221F1F !important;
}

/* Positive delta */
[data-testid="stMetricDelta"] svg {
    fill: #56A66F !important;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #205C50 !important;
}

section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span {
    color: white !important;
}

section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] select,
section[data-testid="stSidebar"] [data-baseweb] {
    color: #221F1F !important;
}

/* Divider */
hr {
    border-color: #84BEA1 !important;
}
</style>
"""


@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    """Load download data from GitHub raw URL or local file.

    Returns:
        DataFrame with parsed dates and labeled platforms.
    """
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


def render_today_summary(df: pd.DataFrame) -> None:
    """Render a Today's Summary section for daily reporting."""
    latest_date = df["report_date"].max()
    today_df = df[df["report_date"] == latest_date]

    # Yesterday's data for comparison
    yesterday = latest_date - pd.Timedelta(days=1)
    yesterday_df = df[df["report_date"] == yesterday]

    st.subheader(f"📅 Today's Report — {latest_date.strftime('%B %d, %Y')}")

    # Per-platform breakdown
    cols = st.columns(3)

    platforms = [("🍎", "App Store", "appstore"), ("🤖", "Google Play", "googleplay")]
    total_today = 0
    total_yesterday = 0

    for i, (icon, label, key) in enumerate(platforms):
        today_row = today_df[today_df["platform"] == key]
        yest_row = yesterday_df[yesterday_df["platform"] == key]

        today_dl = int(today_row["daily_downloads"].sum()) if not today_row.empty else 0
        today_cum = int(today_row["cumulative_total"].iloc[-1]) if not today_row.empty else 0
        yest_dl = int(yest_row["daily_downloads"].sum()) if not yest_row.empty else 0

        delta = today_dl - yest_dl if yest_dl > 0 else None
        total_today += today_dl
        total_yesterday += yest_dl

        with cols[i]:
            st.metric(
                f"{icon} {label}",
                f"{today_dl:,}",
                delta=f"{delta:+,} vs yesterday" if delta is not None else None,
            )
            st.caption(f"Cumulative: **{today_cum:,}**")

    # Combined total
    with cols[2]:
        combined_delta = total_today - total_yesterday if total_yesterday > 0 else None
        # Grand total cumulative
        grand_total = int(today_df["cumulative_total"].sum()) if not today_df.empty else 0
        st.metric(
            "📦 Combined",
            f"{total_today:,}",
            delta=f"{combined_delta:+,} vs yesterday" if combined_delta is not None else None,
        )
        st.caption(f"Grand Total: **{grand_total:,}**")

    # Week-over-week context
    daily_combined = df.groupby("report_date")["daily_downloads"].sum().sort_index()
    avg_7 = daily_combined.tail(7).mean()
    avg_30 = daily_combined.tail(30).mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Today Total", f"{total_today:,}")
    c2.metric("7-Day Avg", f"{avg_7:,.1f}")
    c3.metric("30-Day Avg", f"{avg_30:,.1f}")
    pct_vs_avg = ((total_today / avg_7) - 1) * 100 if avg_7 > 0 else 0
    c4.metric("vs 7-Day Avg", f"{pct_vs_avg:+.0f}%")


def render_kpi_cards(df: pd.DataFrame) -> None:
    """Render KPI metric cards at the top of the dashboard."""
    total = int(df["daily_downloads"].sum())
    latest_date = df["report_date"].max()
    today_df = df[df["report_date"] == latest_date]
    today_total = int(today_df["daily_downloads"].sum()) if not today_df.empty else 0

    # Daily combined for averages
    daily_combined = df.groupby("report_date")["daily_downloads"].sum().sort_index()
    avg_7 = daily_combined.tail(7).mean()
    avg_30 = daily_combined.tail(30).mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Downloads", f"{total:,}")
    c2.metric("Latest Day", f"{today_total:,}")
    c3.metric("7-Day Avg", f"{avg_7:,.1f}")
    c4.metric("30-Day Avg", f"{avg_30:,.1f}")


def render_daily_chart(df: pd.DataFrame) -> None:
    """Daily downloads line chart by platform + combined."""
    daily = df.groupby(["report_date", "platform_label"])["daily_downloads"].sum().reset_index()

    # Combined line
    combined = df.groupby("report_date")["daily_downloads"].sum().reset_index()
    combined["platform_label"] = "Combined"

    chart_df = pd.concat([daily, combined], ignore_index=True)

    fig = px.line(
        chart_df,
        x="report_date",
        y="daily_downloads",
        color="platform_label",
        title="Daily Downloads",
        labels={"report_date": "Date", "daily_downloads": "Downloads", "platform_label": "Platform"},
        color_discrete_map=PLATFORM_COLORS,
    )
    fig.update_layout(hovermode="x unified", font_family="Poppins")
    st.plotly_chart(fig, use_container_width=True)


def render_cumulative_chart(df: pd.DataFrame) -> None:
    """Stacked area chart of cumulative downloads."""
    cum = df.sort_values("report_date")
    fig = px.area(
        cum,
        x="report_date",
        y="cumulative_total",
        color="platform_label",
        title="Cumulative Growth",
        labels={"report_date": "Date", "cumulative_total": "Total Downloads", "platform_label": "Platform"},
        color_discrete_map=PLATFORM_COLORS,
    )
    fig.update_layout(font_family="Poppins")
    st.plotly_chart(fig, use_container_width=True)


def render_moving_avg_chart(df: pd.DataFrame) -> None:
    """7-day moving average trend line."""
    daily = df.groupby(["report_date", "platform_label"])["daily_downloads"].sum().reset_index()

    fig = go.Figure()
    for platform in daily["platform_label"].unique():
        pdf = daily[daily["platform_label"] == platform].sort_values("report_date")
        pdf["ma7"] = pdf["daily_downloads"].rolling(7, min_periods=1).mean()
        fig.add_trace(go.Scatter(
            x=pdf["report_date"], y=pdf["ma7"],
            mode="lines", name=platform,
            line=dict(color=PLATFORM_COLORS.get(platform)),
        ))

    # Combined
    combined = daily.groupby("report_date")["daily_downloads"].sum().reset_index().sort_values("report_date")
    combined["ma7"] = combined["daily_downloads"].rolling(7, min_periods=1).mean()
    fig.add_trace(go.Scatter(
        x=combined["report_date"], y=combined["ma7"],
        mode="lines", name="Combined", line=dict(dash="dash", color=BT_PALE_ORANGE),
    ))

    fig.update_layout(title="7-Day Moving Average", hovermode="x unified",
                      xaxis_title="Date", yaxis_title="Downloads (7d avg)",
                      font_family="Poppins")
    st.plotly_chart(fig, use_container_width=True)


def render_pie_chart(df: pd.DataFrame) -> None:
    """Platform split pie chart."""
    totals = df.groupby("platform_label")["daily_downloads"].sum().reset_index()
    fig = px.pie(
        totals,
        values="daily_downloads",
        names="platform_label",
        title="Platform Split",
        color="platform_label",
        color_discrete_map=PLATFORM_COLORS,
    )
    fig.update_layout(font_family="Poppins")
    st.plotly_chart(fig, use_container_width=True)


def main() -> None:
    """Entry point for the Streamlit dashboard."""
    st.set_page_config(page_title="B-Ticket Downloads", page_icon="📊", layout="wide")
    st.markdown(BRAND_CSS, unsafe_allow_html=True)
    st.title("📊 B-Ticket Download Dashboard")

    df = load_data()

    # --- Today's Summary (always visible) ---
    render_today_summary(df)
    st.divider()

    # --- Sidebar filters ---
    st.sidebar.header("Filters")

    min_date = df["report_date"].min().date()
    max_date = df["report_date"].max().date()
    date_range = st.sidebar.date_input(
        "Date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

    platform_options = ["All", "App Store", "Google Play"]
    platform_filter = st.sidebar.selectbox("Platform", platform_options)

    # --- Apply filters ---
    filtered = df.copy()
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
        filtered = filtered[(filtered["report_date"] >= start) & (filtered["report_date"] <= end)]

    if platform_filter != "All":
        filtered = filtered[filtered["platform_label"] == platform_filter]

    if filtered.empty:
        st.warning("No data for the selected filters.")
        return

    # --- Render ---
    render_kpi_cards(filtered)
    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        render_daily_chart(filtered)
    with col2:
        render_cumulative_chart(filtered)

    col3, col4 = st.columns(2)
    with col3:
        render_moving_avg_chart(filtered)
    with col4:
        render_pie_chart(filtered)

    # Footer
    st.caption(f"Data range: {min_date} → {max_date} · {len(df)} records")


if __name__ == "__main__":
    main()
