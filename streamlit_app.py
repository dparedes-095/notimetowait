import json
from datetime import datetime, timedelta, timezone

import altair as alt
import boto3
import pandas as pd
import requests
import streamlit as st


# -----------------------------
# Config
# -----------------------------
PARK_ID = 334
URL = f"https://queue-times.com/en-US/parks/{PARK_ID}/queue_times.json"
EASTERN_TZ = "America/New_York"
ALERTS_KEY = "epic-universe/alerts/active_alerts.json"

st.set_page_config(
    page_title="Epic Universe Waits",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    .main {
        background-color: #eaf4ff;
    }

    .block-container {
        padding-top: 1.5rem;
    }

    .chart-card {
        background: #f8fafc;
        border: 2px solid #a8a8a8;
        border-radius: 20px;
        padding: 20px;
        margin-bottom: 24px;
        box-shadow: 2px 4px 8px rgba(0,0,0,0.18);
    }

    .small-badge {
        display: inline-block;
        border: 2px solid #a8a8a8;
        border-radius: 8px;
        padding: 3px 8px;
        color: #777;
        font-size: 0.8rem;
        font-weight: 700;
        margin-bottom: 10px;
        background: white;
    }

    h1, h2, h3 {
        color: #003b70;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🎢 Epic Universe Wait Times")
st.caption("Live queue data from Queue-Times.com | Historical snapshots from your S3 collector")


# -----------------------------
# Manual refresh
# -----------------------------
if st.button("Refresh data"):
    st.cache_data.clear()
    st.rerun()


# -----------------------------
# Live API fetch
# -----------------------------
@st.cache_data(ttl=300)
def fetch_wait_times():
    response = requests.get(URL, timeout=10)
    response.raise_for_status()
    data = response.json()

    rows = []

    for land in data.get("lands", []):
        land_id = land.get("id")
        land_name = land.get("name")

        for ride in land.get("rides", []):
            ride_name = ride.get("name", "")

            rows.append({
                "land_id": land_id,
                "land_name": land_name,
                "ride_id": ride.get("id"),
                "ride_name": ride_name,
                "is_open": ride.get("is_open"),
                "wait_time": ride.get("wait_time"),
                "last_updated_utc": ride.get("last_updated"),
                "is_single_rider": "single rider" in ride_name.lower(),
            })

    df = pd.DataFrame(rows)

    if not df.empty:
        df["last_updated_eastern"] = (
            pd.to_datetime(df["last_updated_utc"], utc=True, errors="coerce")
            .dt.tz_convert(EASTERN_TZ)
        )
        df["wait_time"] = pd.to_numeric(df["wait_time"], errors="coerce")

    return df


# -----------------------------
# S3 helpers
# -----------------------------
def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
        region_name=st.secrets.get("AWS_DEFAULT_REGION", "us-east-2"),
    )


@st.cache_data(ttl=300)
def load_s3_history(days_back=30):
    bucket = st.secrets["S3_BUCKET"]
    prefix = st.secrets["S3_PREFIX"].rstrip("/")

    s3 = get_s3_client()

    objects = []
    continuation_token = None

    while True:
        kwargs = {
            "Bucket": bucket,
            "Prefix": prefix,
            "MaxKeys": 1000,
        }

        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        response = s3.list_objects_v2(**kwargs)

        for obj in response.get("Contents", []):
            key = obj["Key"]

            if key.endswith(".json"):
                objects.append({
                    "key": key,
                    "last_modified": obj["LastModified"],
                })

        if response.get("IsTruncated"):
            continuation_token = response.get("NextContinuationToken")
        else:
            break

    if not objects:
        return pd.DataFrame()

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    recent_objects = [
        obj for obj in objects
        if obj["last_modified"] >= cutoff
    ]

    rows = []

    for obj in recent_objects:
        file_obj = s3.get_object(Bucket=bucket, Key=obj["key"])
        payload = json.loads(file_obj["Body"].read().decode("utf-8"))

        for ride in payload.get("rides", []):
            ride = ride.copy()
            ride["s3_key"] = obj["key"]
            ride["s3_last_modified"] = obj["last_modified"].isoformat()
            rows.append(ride)

    history_df = pd.DataFrame(rows)

    if history_df.empty:
        return history_df

    history_df["collected_at_eastern"] = (
        pd.to_datetime(history_df["collected_at_eastern"], utc=True, errors="coerce")
        .dt.tz_convert(EASTERN_TZ)
    )

    history_df["last_updated_eastern"] = (
        pd.to_datetime(history_df["last_updated_eastern"], utc=True, errors="coerce")
        .dt.tz_convert(EASTERN_TZ)
    )

    history_df["collection_date_eastern"] = history_df["collected_at_eastern"].dt.date
    history_df["collection_hour_eastern"] = history_df["collected_at_eastern"].dt.hour
    history_df["collection_weekday_eastern"] = history_df["collected_at_eastern"].dt.day_name()
    history_df["wait_time"] = pd.to_numeric(history_df["wait_time"], errors="coerce")

    return history_df


def load_alerts_from_s3():
    s3 = get_s3_client()
    bucket = st.secrets["S3_BUCKET"]

    try:
        obj = s3.get_object(Bucket=bucket, Key=ALERTS_KEY)
        return json.loads(obj["Body"].read().decode("utf-8"))
    except s3.exceptions.NoSuchKey:
        return []
    except Exception:
        return []


def save_alerts_to_s3(alerts):
    s3 = get_s3_client()
    bucket = st.secrets["S3_BUCKET"]

    s3.put_object(
        Bucket=bucket,
        Key=ALERTS_KEY,
        Body=json.dumps(alerts, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def create_or_restart_alert(ride_id, ride_name):
    now = pd.Timestamp.now(tz=EASTERN_TZ)
    today = now.date().isoformat()

    alerts = load_alerts_from_s3()

    existing = None
    for alert in alerts:
        if alert.get("ride_id") == ride_id:
            existing = alert
            break

    adaptive_threshold_fields = {
        "threshold_mode": "adaptive",
        "threshold_percent_below_avg": 0.25,
        "threshold_min_minutes": 8,
        "threshold_max_minutes": 25,
    }

    if existing:
        existing_date = existing.get("created_date_eastern")
        existing_status = existing.get("status")

        if existing_date == today and existing_status == "active":
            return "already_active"

        existing.update({
            "ride_id": int(ride_id),
            "ride_name": ride_name,
            "alert_type": "optimal_same_hour",
            **adaptive_threshold_fields,
            "created_at_eastern": now.isoformat(),
            "created_date_eastern": today,
            "expires_date_eastern": today,
            "status": "active",
            "triggered_at_eastern": None,
            "last_checked_at_eastern": None,
        })

        save_alerts_to_s3(alerts)
        return "restarted"

    new_alert = {
        "ride_id": int(ride_id),
        "ride_name": ride_name,
        "alert_type": "optimal_same_hour",
        **adaptive_threshold_fields,
        "created_at_eastern": now.isoformat(),
        "created_date_eastern": today,
        "expires_date_eastern": today,
        "status": "active",
        "triggered_at_eastern": None,
        "last_checked_at_eastern": None,
    }

    alerts.append(new_alert)
    save_alerts_to_s3(alerts)

    return "created"


# -----------------------------
# Helpers
# -----------------------------
def format_hour(hour):
    hour = int(hour)
    suffix = "AM" if hour < 12 else "PM"
    hour_12 = hour % 12

    if hour_12 == 0:
        hour_12 = 12

    return f"{hour_12:02d}:00 {suffix}"


def is_inside_park_hours(timestamp_eastern):
    """
    Park hours rule:
    - Friday: 8 AM to 9 PM
    - All other days: 10 AM to 9 PM

    End hour is exclusive, so 9 PM and later is outside park hours.
    """
    if pd.isna(timestamp_eastern):
        return False

    weekday = timestamp_eastern.day_name()
    hour = timestamp_eastern.hour

    if weekday == "Friday":
        return 8 <= hour < 21

    return 10 <= hour < 21


def recommendation(current_wait, same_hour_avg, next_hour_avg, is_open):
    if not is_open:
        return "Closed"

    if pd.isna(same_hour_avg):
        return "Need history"

    diff = current_wait - same_hour_avg

    if pd.notna(next_hour_avg):
        if next_hour_avg <= current_wait - 15:
            return "Wait"
        if current_wait <= next_hour_avg - 15:
            return "Ride now"

    if diff <= -15:
        return "Great time"
    if diff <= 10:
        return "Normal"
    if diff <= 25:
        return "Maybe wait"

    return "Wait"


def recommendation_context(current_wait, same_hour_avg, next_hour_avg, is_open):
    if not is_open:
        return "Currently closed"

    if pd.isna(same_hour_avg):
        return "More history needed"

    diff = current_wait - same_hour_avg

    if pd.notna(next_hour_avg):
        next_diff = next_hour_avg - current_wait

        if next_diff <= -15:
            return f"Next hour may be better ({next_hour_avg:.0f} min avg)"

        if next_diff >= 15:
            return f"Now beats next hour ({next_hour_avg:.0f} min avg)"

    if diff <= -15:
        return f"{abs(diff):.0f} min below normal"

    if diff <= -5:
        return "Slightly below normal"

    if diff <= 10:
        return "Typical for this hour"

    if diff <= 25:
        return f"{diff:.0f} min above normal"

    return "Much higher than normal"


# -----------------------------
# Load live data
# -----------------------------
try:
    live_df = fetch_wait_times()
except Exception as e:
    st.error("Could not fetch live Queue-Times data.")
    st.exception(e)
    st.stop()


# -----------------------------
# Sidebar filters
# -----------------------------
st.sidebar.header("Filters")

hide_single_rider = st.sidebar.toggle("Hide single rider", value=True)

current_open_only = st.sidebar.toggle(
    "Current table: open rides only",
    value=False,
)

history_days = st.sidebar.slider(
    "History window",
    min_value=1,
    max_value=30,
    value=30,
)

lands = ["All"] + sorted(live_df["land_name"].dropna().unique().tolist())
selected_land = st.sidebar.selectbox("Land", lands)


# -----------------------------
# Live filters
# -----------------------------
live_filtered = live_df.copy()

if hide_single_rider:
    live_filtered = live_filtered[~live_filtered["is_single_rider"]]

if current_open_only:
    live_filtered = live_filtered[live_filtered["is_open"] == True]

if selected_land != "All":
    live_filtered = live_filtered[live_filtered["land_name"] == selected_land]


# -----------------------------
# Current metrics
# -----------------------------
st.subheader("Right Now")

open_live_for_metrics = live_filtered[live_filtered["is_open"] == True].copy()

col1, col2, col3, col4 = st.columns(4)

avg_wait = open_live_for_metrics["wait_time"].mean()
max_wait = open_live_for_metrics["wait_time"].max()
open_count = live_filtered["is_open"].sum()
last_updated = live_filtered["last_updated_eastern"].max()

col1.metric("Avg Open Wait", f"{avg_wait:.0f} min" if pd.notna(avg_wait) else "N/A")
col2.metric("Longest Open Wait", f"{max_wait:.0f} min" if pd.notna(max_wait) else "N/A")
col3.metric("Open Attractions", int(open_count))
col4.metric(
    "Last Updated",
    last_updated.strftime("%I:%M %p %Z") if pd.notna(last_updated) else "N/A",
)

if open_live_for_metrics.empty:
    st.warning(
        "Most or all attractions appear closed right now. "
        "Live recommendations are paused, but historical charts are still useful."
    )

st.divider()


# -----------------------------
# Current queue table
# -----------------------------
st.subheader("Current Queue Times")

current_table = live_filtered[[
    "land_name",
    "ride_name",
    "wait_time",
    "is_open",
    "last_updated_eastern",
]].copy()

current_table["display_wait"] = current_table.apply(
    lambda row: f"{int(row['wait_time'])} min"
    if row["is_open"] and pd.notna(row["wait_time"])
    else "Closed",
    axis=1,
)

current_table = current_table.sort_values(
    ["is_open", "wait_time"],
    ascending=[False, False],
)

current_table = current_table[[
    "land_name",
    "ride_name",
    "display_wait",
    "is_open",
    "last_updated_eastern",
]]

current_table = current_table.rename(columns={
    "land_name": "Land",
    "ride_name": "Ride",
    "display_wait": "Wait",
    "is_open": "Open",
    "last_updated_eastern": "Updated",
})

st.dataframe(current_table, use_container_width=True, hide_index=True)

st.divider()


# -----------------------------
# Load S3 history
# -----------------------------
try:
    history_df = load_s3_history(days_back=history_days)
except Exception as e:
    st.error("Could not load S3 history.")
    st.exception(e)
    st.stop()

if history_df.empty:
    st.info("No historical S3 snapshots found yet. Let the Lambda collector run a few times.")
    st.stop()


# -----------------------------
# Historical filters
# -----------------------------
history_filtered = history_df.copy()

if hide_single_rider:
    history_filtered = history_filtered[~history_filtered["is_single_rider"]]

if selected_land != "All":
    history_filtered = history_filtered[history_filtered["land_name"] == selected_land]

history_filtered["inside_park_hours"] = history_filtered["collected_at_eastern"].apply(
    is_inside_park_hours
)

# Historical wait averages only use valid observations from when rides were open and during park hours.
# Important: exclude 0-minute waits so downtime/closed-status zeros do not drag averages down.
history_filtered = history_filtered[
    (history_filtered["inside_park_hours"] == True) &
    (history_filtered["is_open"] == True) &
    (history_filtered["wait_time"].notna()) &
    (history_filtered["wait_time"] > 0)
].copy()

if history_filtered.empty:
    st.warning(
        "Historical data loaded, but there are no valid open-ride, in-hours wait observations "
        "after your filters."
    )
    st.stop()

st.caption(
    f"Using {len(history_filtered):,} valid open-ride, in-hours snapshot rows from the last "
    f"{history_days} day(s)."
)


# -----------------------------
# Decision table
# -----------------------------
st.subheader("Should I Ride Now?")

current_hour = pd.Timestamp.now(tz=EASTERN_TZ).hour
next_hour = (current_hour + 1) % 24

# Same-hour and next-hour averages
hourly_avg = (
    history_filtered
    .groupby(["ride_id", "ride_name", "collection_hour_eastern"], as_index=False)
    .agg(
        historical_hour_avg=("wait_time", "mean"),
        samples=("wait_time", "count"),
    )
)

same_hour_avg = hourly_avg[
    hourly_avg["collection_hour_eastern"] == current_hour
].copy()

same_hour_avg = same_hour_avg.rename(columns={
    "historical_hour_avg": "same_hour_avg",
    "samples": "same_hour_samples",
})

next_hour_avg = hourly_avg[
    hourly_avg["collection_hour_eastern"] == next_hour
].copy()

next_hour_avg = next_hour_avg.rename(columns={
    "historical_hour_avg": "next_hour_avg",
    "samples": "next_hour_samples",
})

# Overall historical average across the selected history window
overall_avg = (
    history_filtered
    .groupby(["ride_id", "ride_name"], as_index=False)
    .agg(
        overall_avg_wait=("wait_time", "mean"),
        overall_samples=("wait_time", "count"),
    )
)

comparison_base = live_df.copy()

if hide_single_rider:
    comparison_base = comparison_base[~comparison_base["is_single_rider"]]

if selected_land != "All":
    comparison_base = comparison_base[comparison_base["land_name"] == selected_land]

comparison = comparison_base.merge(
    same_hour_avg[["ride_id", "same_hour_avg", "same_hour_samples"]],
    on="ride_id",
    how="left",
)

comparison = comparison.merge(
    next_hour_avg[["ride_id", "next_hour_avg", "next_hour_samples"]],
    on="ride_id",
    how="left",
)

comparison = comparison.merge(
    overall_avg[["ride_id", "overall_avg_wait", "overall_samples"]],
    on="ride_id",
    how="left",
)

comparison["difference_vs_same_hour"] = (
    comparison["wait_time"] - comparison["same_hour_avg"]
)

comparison["difference_vs_overall"] = (
    comparison["wait_time"] - comparison["overall_avg_wait"]
)

comparison["recommendation"] = comparison.apply(
    lambda row: recommendation(
        row["wait_time"],
        row["same_hour_avg"],
        row["next_hour_avg"],
        row["is_open"],
    ),
    axis=1,
)

comparison["context"] = comparison.apply(
    lambda row: recommendation_context(
        row["wait_time"],
        row["same_hour_avg"],
        row["next_hour_avg"],
        row["is_open"],
    ),
    axis=1,
)

open_opportunity_df = comparison[
    (comparison["is_open"] == True) &
    (comparison["difference_vs_same_hour"].notna())
].copy()

if not open_opportunity_df.empty:
    best = open_opportunity_df.sort_values("difference_vs_same_hour").iloc[0]

    b1, b2, b3, b4 = st.columns(4)

    b1.metric("Best Opportunity", best["ride_name"])
    b2.metric("Current Wait", f"{best['wait_time']:.0f} min")
    b3.metric("Vs Hour Avg", f"{best['difference_vs_same_hour']:.0f} min")

    if pd.notna(best["difference_vs_overall"]):
        b4.metric("Vs 30D Avg", f"{best['difference_vs_overall']:.0f} min")
    else:
        b4.metric("Vs 30D Avg", "N/A")
else:
    st.info("No open rides have enough same-hour history for an opportunity score right now.")

decision_table = comparison[[
    "land_name",
    "ride_name",
    "is_open",
    "wait_time",
    "same_hour_avg",
    "difference_vs_same_hour",
    "overall_avg_wait",
    "difference_vs_overall",
    "next_hour_avg",
    "recommendation",
    "context",
]].copy()

decision_table["Current Wait"] = decision_table.apply(
    lambda row: f"{int(row['wait_time'])} min"
    if row["is_open"] and pd.notna(row["wait_time"])
    else "Closed",
    axis=1,
)

decision_table["same_hour_avg"] = decision_table["same_hour_avg"].apply(
    lambda x: f"{x:.0f} min" if pd.notna(x) else "N/A"
)

decision_table["overall_avg_wait"] = decision_table["overall_avg_wait"].apply(
    lambda x: f"{x:.0f} min" if pd.notna(x) else "N/A"
)

decision_table = decision_table.sort_values(
    ["is_open", "difference_vs_same_hour"],
    ascending=[False, True],
    na_position="last",
)

decision_table = decision_table[[
    "land_name",
    "ride_name",
    "Current Wait",
    "same_hour_avg",
    "overall_avg_wait",
    "recommendation",
    "context",
]]

decision_table = decision_table.rename(columns={
    "land_name": "Land",
    "ride_name": "Ride",
    "same_hour_avg": "Hour Avg",
    "overall_avg_wait": "30D Avg",
    "recommendation": "Rec",
    "context": "Context",
})

st.dataframe(decision_table, use_container_width=True, hide_index=True)


# -----------------------------
# Notify section
# -----------------------------
st.divider()
st.subheader("Notify Me When Optimal")

st.caption(
    "Choose a ride to watch for today. You’ll get one alert when it becomes meaningfully "
    "better than its same-hour average during park hours. The threshold adapts by ride."
)

alert_ride_options = (
    comparison_base[
        (comparison_base["is_open"] == True) &
        (~comparison_base["is_single_rider"])
    ][["ride_id", "ride_name", "land_name"]]
    .drop_duplicates()
    .sort_values("ride_name")
)

if alert_ride_options.empty:
    st.info("No open rides available for alerts right now.")
else:
    alert_labels = {
        f"{row['ride_name']} — {row['land_name']}": {
            "ride_id": row["ride_id"],
            "ride_name": row["ride_name"],
        }
        for _, row in alert_ride_options.iterrows()
    }

    selected_alert_label = st.selectbox(
        "Ride to watch",
        list(alert_labels.keys()),
        key="alert_ride_select",
    )

    selected_alert = alert_labels[selected_alert_label]

    if st.button("Notify When Optimal", key="notify_when_optimal"):
        try:
            result = create_or_restart_alert(
                selected_alert["ride_id"],
                selected_alert["ride_name"],
            )

            if result == "already_active":
                st.info("Already watching this ride today.")
            elif result == "restarted":
                st.success("Restarted watch for today.")
            else:
                st.success("Alert successful! I’ll notify you if it becomes optimal.")
        except Exception as e:
            st.error("Could not save alert rule to S3.")
            st.exception(e)

st.divider()


# -----------------------------
# Chart 1: Daily average wait + rolling average
# -----------------------------
st.subheader("📊 Epic Universe Average Wait Time")

daily_avg = (
    history_filtered
    .groupby("collection_date_eastern", as_index=False)
    .agg(avg_wait=("wait_time", "mean"))
    .sort_values("collection_date_eastern")
)

daily_avg["collection_date_eastern"] = pd.to_datetime(daily_avg["collection_date_eastern"])
daily_avg["rolling_avg"] = daily_avg["avg_wait"].rolling(window=7, min_periods=1).mean()

latest_date = daily_avg["collection_date_eastern"].max().strftime("%m/%d/%Y")

st.markdown(
    f"""
    <div class="chart-card">
    <span class="small-badge">DATA THROUGH {latest_date}</span>
    """,
    unsafe_allow_html=True,
)

bars = (
    alt.Chart(daily_avg)
    .mark_bar()
    .encode(
        x=alt.X("collection_date_eastern:T", title="Date"),
        y=alt.Y("avg_wait:Q", title="Wait Time (minutes)"),
        color=alt.Color(
            "avg_wait:Q",
            scale=alt.Scale(scheme="redyellowgreen", reverse=True),
            legend=None,
        ),
        tooltip=[
            alt.Tooltip("collection_date_eastern:T", title="Date"),
            alt.Tooltip("avg_wait:Q", title="Avg Wait", format=".1f"),
        ],
    )
)

rolling = (
    alt.Chart(daily_avg)
    .mark_line(color="#555555", strokeWidth=3)
    .encode(
        x="collection_date_eastern:T",
        y="rolling_avg:Q",
        tooltip=[
            alt.Tooltip("collection_date_eastern:T", title="Date"),
            alt.Tooltip("rolling_avg:Q", title="Rolling Avg", format=".1f"),
        ],
    )
)

st.altair_chart((bars + rolling).properties(height=380), use_container_width=True)

st.markdown("</div>", unsafe_allow_html=True)


# -----------------------------
# Chart 2: Hourly heat map
# -----------------------------
st.subheader("🔥 Epic Universe Wait Time Heat Map")

heatmap_df = (
    history_filtered
    .groupby(["ride_name", "collection_hour_eastern"], as_index=False)
    .agg(avg_wait=("wait_time", "mean"))
)

ride_order = (
    heatmap_df
    .groupby("ride_name", as_index=False)
    .agg(overall_avg=("avg_wait", "mean"))
    .sort_values("overall_avg", ascending=False)["ride_name"]
    .tolist()
)

heatmap_df["hour_label"] = heatmap_df["collection_hour_eastern"].apply(format_hour)
heatmap_df["avg_wait_label"] = heatmap_df["avg_wait"].round(0).astype(int).astype(str)

st.markdown(
    f"""
    <div class="chart-card">
    <span class="small-badge">DATA THROUGH {latest_date}</span>
    """,
    unsafe_allow_html=True,
)

base = (
    alt.Chart(heatmap_df)
    .encode(
        x=alt.X(
            "hour_label:N",
            title="Hour",
            sort=[format_hour(h) for h in range(24)],
            axis=alt.Axis(labelAngle=-45),
        ),
        y=alt.Y(
            "ride_name:N",
            title="Ride",
            sort=ride_order,
        ),
    )
)

heatmap = base.mark_rect().encode(
    color=alt.Color(
        "avg_wait:Q",
        title="Wait Time",
        scale=alt.Scale(scheme="redyellowgreen", reverse=True),
    ),
    tooltip=[
        alt.Tooltip("ride_name:N", title="Ride"),
        alt.Tooltip("hour_label:N", title="Hour"),
        alt.Tooltip("avg_wait:Q", title="Avg Wait", format=".1f"),
    ],
)

text = base.mark_text(fontSize=10).encode(
    text="avg_wait_label:N",
    color=alt.condition(
        alt.datum.avg_wait > 70,
        alt.value("white"),
        alt.value("black"),
    ),
)

st.altair_chart(
    (heatmap + text).properties(height=max(360, len(ride_order) * 28)),
    use_container_width=True,
)

st.markdown("</div>", unsafe_allow_html=True)


# -----------------------------
# Chart 3: Selected ride wait profile
# -----------------------------
st.subheader("📈 Epic Universe Wait Time Profile")

ride_options = sorted(history_filtered["ride_name"].dropna().unique().tolist())

selected_ride = st.selectbox(
    "Select ride",
    ride_options,
    key="selected_ride_profile",
)

available_dates = sorted(history_filtered["collection_date_eastern"].dropna().unique().tolist())

selected_date = st.selectbox(
    "Selected date for posted wait points",
    available_dates,
    index=len(available_dates) - 1,
    key="selected_profile_date",
)

ride_history = history_filtered[history_filtered["ride_name"] == selected_ride].copy()

typical_wait = (
    ride_history
    .groupby("collection_hour_eastern", as_index=False)
    .agg(typical_wait=("wait_time", "mean"))
    .sort_values("collection_hour_eastern")
)

selected_day_points = ride_history[
    ride_history["collection_date_eastern"] == selected_date
].copy()

selected_day_points["time_of_day"] = selected_day_points["collected_at_eastern"].dt.tz_localize(None)

base_date = pd.to_datetime(selected_date)

typical_wait["time_of_day"] = typical_wait["collection_hour_eastern"].apply(
    lambda h: base_date + pd.Timedelta(hours=int(h))
)

selected_date_label = pd.to_datetime(selected_date).strftime("%m/%d/%Y")

st.markdown(
    f"""
    <div class="chart-card">
    <span class="small-badge">DATA FOR {selected_date_label}</span>
    """,
    unsafe_allow_html=True,
)

typical_line = (
    alt.Chart(typical_wait)
    .mark_line(strokeDash=[8, 6], strokeWidth=3, color="#888888")
    .encode(
        x=alt.X("time_of_day:T", title="Time of Day"),
        y=alt.Y("typical_wait:Q", title="Wait Time (minutes)"),
        tooltip=[
            alt.Tooltip("collection_hour_eastern:Q", title="Hour"),
            alt.Tooltip("typical_wait:Q", title="Typical Wait", format=".1f"),
        ],
    )
)

posted_points = (
    alt.Chart(selected_day_points)
    .mark_circle(size=85, color="#4c9aff", opacity=0.8)
    .encode(
        x="time_of_day:T",
        y=alt.Y("wait_time:Q", title="Wait Time (minutes)"),
        tooltip=[
            alt.Tooltip("ride_name:N", title="Ride"),
            alt.Tooltip("time_of_day:T", title="Snapshot Time"),
            alt.Tooltip("wait_time:Q", title="Posted Wait"),
        ],
    )
)

posted_line = (
    alt.Chart(selected_day_points)
    .mark_line(color="#4c9aff", opacity=0.45)
    .encode(
        x="time_of_day:T",
        y="wait_time:Q",
    )
)

st.altair_chart(
    (typical_line + posted_line + posted_points).properties(height=400),
    use_container_width=True,
)

st.markdown("</div>", unsafe_allow_html=True)


# -----------------------------
# Chart 4: Average wait by weekday
# -----------------------------
st.subheader("📊 Epic Universe Average Wait by Weekday")

weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

weekday_avg = (
    history_filtered
    .groupby("collection_weekday_eastern", as_index=False)
    .agg(avg_wait=("wait_time", "mean"))
)

weekday_avg["weekday_sort"] = weekday_avg["collection_weekday_eastern"].apply(
    lambda x: weekday_order.index(x) if x in weekday_order else 99
)

weekday_avg = weekday_avg.sort_values("weekday_sort")

st.markdown(
    f"""
    <div class="chart-card">
    <span class="small-badge">DATA THROUGH {latest_date}</span>
    """,
    unsafe_allow_html=True,
)

weekday_chart = (
    alt.Chart(weekday_avg)
    .mark_bar()
    .encode(
        x=alt.X(
            "collection_weekday_eastern:N",
            title="Weekday",
            sort=weekday_order,
            axis=alt.Axis(labelAngle=-45),
        ),
        y=alt.Y("avg_wait:Q", title="Wait Time (minutes)"),
        color=alt.Color(
            "avg_wait:Q",
            scale=alt.Scale(scheme="redyellowgreen", reverse=True),
            legend=None,
        ),
        tooltip=[
            alt.Tooltip("collection_weekday_eastern:N", title="Weekday"),
            alt.Tooltip("avg_wait:Q", title="Avg Wait", format=".1f"),
        ],
    )
    .properties(height=360)
)

st.altair_chart(weekday_chart, use_container_width=True)

st.markdown("</div>", unsafe_allow_html=True)