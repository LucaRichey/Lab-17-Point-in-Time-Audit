import os
import sys

# Auto-launch wrapper: allows running directly via `python asof_app.py` or the IDE play button
try:
    from streamlit.runtime import exists
    if not exists():
        from streamlit.web import cli as stcli
        sys.argv = ["streamlit", "run", os.path.abspath(__file__)] + sys.argv[1:]
        sys.exit(stcli.main())
except ImportError:
    # If this specific Python interpreter does not have streamlit, locate and exec one that does
    for st_bin in [
        "/usr/local/bin/streamlit",
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/streamlit",
        "/Library/Frameworks/Python.framework/Versions/3.11/bin/streamlit",
        "streamlit"
    ]:
        if os.path.exists(st_bin):
            os.execv(st_bin, [st_bin, "run", os.path.abspath(__file__)] + sys.argv[1:])

import io
import subprocess
import urllib.request
import datetime
import numpy as np
import pandas as pd
import streamlit as st

# Page configuration
st.set_page_config(
    page_title="FRED & ALFRED Interest Rates — Point-in-Time Audit",
    page_icon="📈",
    layout="wide"
)

# Title & Mandated Subtitle
st.title("FRED & ALFRED Interest Rates — Point-in-Time Audit")
st.caption(
    "Data from FRED and ALFRED, Federal Reserve Bank of St. Louis, downloaded today; "
    "built with AI help, a learning demonstration, not investment advice."
)

# Helper function to download CSV with dual-protocol fallback:
# 1. macOS curl with --compressed (fastest, avoids Akamai TLS fingerprint rate-limiting)
# 2. urllib.request standard fallback
def download_csv_text(url: str) -> str:
    try:
        res = subprocess.run(
            ["curl", "-sL", "--compressed", "--max-time", "12", url],
            capture_output=True,
            text=True,
            timeout=15
        )
        if res.returncode == 0 and res.stdout.strip():
            # If the server returned an error HTML or empty body, fail to fallback
            if not res.stdout.strip().startswith("<!DOCTYPE") and not res.stdout.strip().startswith("<html"):
                return res.stdout
    except Exception:
        pass

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")

# Cached FRED Download (Today's values)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fred_today(series_id: str) -> pd.DataFrame:
    series_id = series_id.strip().upper()
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    csv_text = download_csv_text(url)
    df = pd.read_csv(io.StringIO(csv_text))
    if df.empty or len(df.columns) < 2:
        raise ValueError(f"No valid data returned for FRED series '{series_id}'")
    date_col = df.columns[0]
    val_col = df.columns[1]
    # Filter '.' missing observations
    df = df[df[val_col] != "."].copy()
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
    df = df.dropna(subset=[val_col])
    df["date"] = pd.to_datetime(df[date_col])
    df = df.sort_values("date").reset_index(drop=True)
    return df[["date", val_col]].rename(columns={val_col: "val_today"})

# Cached ALFRED Download (Values as known on vintage date)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_alfred_asof(series_id: str, vintage_date: str) -> pd.DataFrame:
    series_id = series_id.strip().upper()
    url = f"https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={series_id}&vintage_date={vintage_date}"
    csv_text = download_csv_text(url)
    df = pd.read_csv(io.StringIO(csv_text))
    if df.empty or len(df.columns) < 2:
        raise ValueError(f"No valid data returned for ALFRED series '{series_id}' on vintage {vintage_date}")
    date_col = df.columns[0]
    val_col = df.columns[1]
    # Filter '.' missing observations
    df = df[df[val_col] != "."].copy()
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
    df = df.dropna(subset=[val_col])
    df["date"] = pd.to_datetime(df[date_col])
    df = df.sort_values("date").reset_index(drop=True)
    return df[["date", val_col]].rename(columns={val_col: "val_asof"})

# Sidebar Configuration
st.sidebar.header("Data Selection & Controls")

# Benchmark series options
BENCHMARK_NAMES = {
    "BAA": "BAA (Moody's Baa corporate bond yield)",
    "FEDFUNDS": "FEDFUNDS (federal funds rate)",
    "DGS10": "DGS10 (10-year Treasury yield)",
    "MORTGAGE30US": "MORTGAGE30US (30-year mortgage rate)"
}

selected_benchmarks = st.sidebar.multiselect(
    label="Series IDs",
    options=list(BENCHMARK_NAMES.keys()),
    default=list(BENCHMARK_NAMES.keys()),
    format_func=lambda x: BENCHMARK_NAMES.get(x, x)
)

custom_series_input = st.sidebar.text_input(
    label="Add any other FRED series ID (e.g. PAYEMS, BAA10Y, DGS2)",
    value=""
)

start_date_val = st.sidebar.date_input(
    label="Start date",
    value=datetime.date(2020, 1, 1)
)

as_known_date_val = st.sidebar.date_input(
    label="As known on date",
    value=datetime.date.today()
)

vintage_date_str = as_known_date_val.strftime("%Y-%m-%d")
start_datetime = pd.to_datetime(start_date_val)

# Combine selected benchmark and typed custom series
all_selected_series = list(selected_benchmarks)
if custom_series_input.strip():
    custom_ids = [s.strip().upper() for s in custom_series_input.replace(",", " ").split() if s.strip()]
    for cid in custom_ids:
        if cid not in all_selected_series:
            all_selected_series.append(cid)

# Date formatting helper ensuring exact match with course anchors (e.g., September 2026, 2 October 2026, 1 October 2026)
def format_display_date(dt: pd.Timestamp, sid: str = "") -> str:
    if pd.isna(dt):
        return "N/A"
    monthly_series = {"BAA", "FEDFUNDS", "PAYEMS", "CPIAUCSL", "INDPRO", "UNRATE"}
    if sid.upper() in monthly_series:
        return f"{dt.strftime('%B %Y')}"
    return f"{dt.strftime('%-d %B %Y')}"

def format_clean_value(val: float) -> str:
    if pd.isna(val):
        return "N/A"
    if abs(val) >= 1000:
        return f"{val:,.0f}"
    return f"{val:.2f}"

# Fetch and audit each series
series_data_today = {}
series_data_asof = {}
series_errors = {}
table_rows = []

for sid in all_selected_series:
    # Attempt FRED download
    try:
        df_t = fetch_fred_today(sid)
        series_data_today[sid] = df_t
    except Exception as e:
        series_errors[sid] = f"FRED download failed: {e}"
        continue

    # Attempt ALFRED download
    try:
        df_a = fetch_alfred_asof(sid, vintage_date_str)
        series_data_asof[sid] = df_a
    except Exception as e:
        series_errors[sid] = f"ALFRED download failed for vintage {vintage_date_str}: {e}"
        continue

    # Metrics calculation
    last_a_row = df_a.iloc[-1]
    last_t_row = df_t.iloc[-1]
    last_a_date = last_a_row["date"]
    last_a_val = last_a_row["val_asof"]
    last_t_date = last_t_row["date"]
    last_t_val = last_t_row["val_today"]

    # Revisions on identical historical measurement dates
    merged = pd.merge(df_a, df_t, on="date")
    revised_count = int((np.abs(merged["val_asof"] - merged["val_today"]) > 1e-4).sum())
    # Values today after the last date known on vintage
    later_count = int((df_t["date"] > last_a_date).sum())

    table_rows.append({
        "Series ID": sid,
        "FRED Link": f"https://fred.stlouisfed.org/series/{sid}",
        "Last Date Known (As-Of)": format_display_date(last_a_date, sid),
        "Value (As-Of)": format_clean_value(last_a_val),
        "Last Date Measured (Today)": format_display_date(last_t_date, sid),
        "Value (Today)": format_clean_value(last_t_val),
        "Values After Last Known": later_count,
        "Values Revised Since": revised_count
    })

# Render any individual series errors while keeping the rest of the application fully operational
if series_errors:
    for sid, err in series_errors.items():
        st.error(f"Error for series '{sid}': {err}")

# Section 1: Line Charts
st.subheader("1. Series Charts (Today's Values from Start Date)")

if not all_selected_series:
    st.info("Select or enter a FRED series ID to visualize rates.")
else:
    # 2-column responsive layout
    chart_cols = st.columns(2)
    col_idx = 0

    for sid in all_selected_series:
        if sid in series_errors:
            continue
        df_t = series_data_today[sid]
        df_chart = df_t[df_t["date"] >= start_datetime].copy()
        df_chart = df_chart.set_index("date")

        last_a_date_str = "N/A"
        if sid in series_data_asof:
            last_a_dt = series_data_asof[sid].iloc[-1]["date"]
            last_a_date_str = format_display_date(last_a_dt, sid)

        series_name = BENCHMARK_NAMES.get(sid, sid)

        with chart_cols[col_idx % 2]:
            st.markdown(f"#### {series_name}")
            st.line_chart(df_chart["val_today"], height=260)
            st.caption(f"**Last date in data known on {vintage_date_str}:** {last_a_date_str}")
            st.markdown("---")
        col_idx += 1

# Section 2: Summary Audit Table
st.subheader("2. Point-in-Time Audit & Revision Summary Table")

if table_rows:
    table_df = pd.DataFrame(table_rows)

    # Interactive table with clickable links
    st.dataframe(
        table_df,
        column_config={
            "FRED Link": st.column_config.LinkColumn(
                "FRED Page",
                display_text=r"https://fred\.stlouisfed\.org/series/(.*)"
            ),
            "Values After Last Known": st.column_config.NumberColumn(
                "Values After Last Known",
                help="How many values today's data has after the last date known then."
            ),
            "Values Revised Since": st.column_config.NumberColumn(
                "Values Revised Since",
                help="How many values on identical measurement dates have been revised since."
            )
        },
        hide_index=True,
        width="stretch"
    )

    # Render Clean Markdown Table for direct copy/paste and audit reporting
    st.markdown("### Audit Table (Direct Markdown)")
    md_lines = [
        "| Series ID | FRED Page | Last Date Known (As-Of) | Value (As-Of) | Last Date Measured (Today) | Value (Today) | Values After Last Known | Values Revised Since |",
        "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|"
    ]
    for r in table_rows:
        md_lines.append(
            f"| **{r['Series ID']}** | [{r['Series ID']}]({r['FRED Link']}) | {r['Last Date Known (As-Of)']} | {r['Value (As-Of)']} | {r['Last Date Measured (Today)']} | {r['Value (Today)']} | {r['Values After Last Known']} | {r['Values Revised Since']} |"
        )
    st.markdown("\n".join(md_lines))
