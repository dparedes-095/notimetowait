import base64
import html
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import altair as alt
import boto3
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components


# -----------------------------
# Config
# -----------------------------
PARK_ID = 334
URL = f"https://queue-times.com/en-US/parks/{PARK_ID}/queue_times.json"
EASTERN_TZ = "America/New_York"
ALERTS_KEY = "epic-universe/alerts/active_alerts.json"
MAP_IMAGE_PATH = "assets/epic_universe_map_overlay_base.png"
MAP_IMAGE_FALLBACK_PATH = "epic_universe_map_overlay_base.png"

OVERLAY_POINTS = [
    {"attraction": "Constellation Carousel", "marker": 2, "land": "Celestial Park", "x_pct": 45.6, "y_pct": 52.6},
    {"attraction": "Stardust Racers", "marker": 1, "land": "Celestial Park", "x_pct": 65.4, "y_pct": 48.6},
    {"attraction": "Curse of the Werewolf", "marker": 12, "land": "Dark Universe", "x_pct": 27.6, "y_pct": 42.8},
    {"attraction": "Monsters Unchained: The Frankenstein Experiment", "marker": 11, "land": "Dark Universe", "x_pct": 27.3, "y_pct": 25.9},
    {"attraction": "Dragon Racer's Rally", "marker": 19, "land": "How to Train Your Dragon - Isle of Berk", "x_pct": 76.1, "y_pct": 64.7},
    {"attraction": "Fyre Drill", "marker": 20, "land": "How to Train Your Dragon - Isle of Berk", "x_pct": 67.9, "y_pct": 74.2},
    {"attraction": "Hiccup's Wing Gliders", "marker": 18, "land": "How to Train Your Dragon - Isle of Berk", "x_pct": 76.9, "y_pct": 68.9},
    {"attraction": "Meet Toothless and Friends", "marker": 23, "land": "How to Train Your Dragon - Isle of Berk", "x_pct": 64.9, "y_pct": 80.4},
    {"attraction": "Bowser Jr. Challenge", "marker": None, "land": "Super Nintendo World", "x_pct": 34.7, "y_pct": 65.5},
    {"attraction": "Mario Kart™: Bowser's Challenge", "marker": 4, "land": "Super Nintendo World", "x_pct": 33.1, "y_pct": 69.4},
    {"attraction": "Mine-Cart Madness™", "marker": 5, "land": "Super Nintendo World", "x_pct": 18.8, "y_pct": 69.8},
    {"attraction": "Yoshi's Adventure™", "marker": 6, "land": "Super Nintendo World", "x_pct": 31.6, "y_pct": 63.4},
    {"attraction": "Harry Potter and the Battle at the Ministry™", "marker": 15, "land": "The Wizarding World of Harry Potter - Ministry of Magic", "x_pct": 69.5, "y_pct": 24.2},
]

st.set_page_config(
    page_title="Epic Universe Day Planner",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    :root {
        --park-bg: #07111f;
        --park-card: rgba(13, 29, 49, 0.78);
        --park-card-soft: rgba(28, 49, 77, 0.58);
        --park-border: rgba(165, 190, 220, 0.24);
        --park-border-strong: rgba(216, 188, 123, 0.44);
        --park-text-muted: rgba(245, 247, 250, 0.72);
        --park-gold: #d8bc7b;
        --park-blue: #5aa9ff;
        --park-green: #4ade80;
        --park-red: #fb7185;
    }

    .stApp {
        background:
            radial-gradient(circle at top left, rgba(82, 128, 196, 0.28), transparent 34rem),
            radial-gradient(circle at top right, rgba(216, 188, 123, 0.12), transparent 30rem),
            linear-gradient(180deg, #07111f 0%, #0a1423 48%, #07111f 100%);
    }

    .block-container {
        padding-top: 1.15rem;
        padding-bottom: 2.5rem;
        max-width: 1280px;
    }

    h1, h2, h3 {
        letter-spacing: -0.035em;
    }

    div[data-testid="stVerticalBlock"] > div:has(.hero-card),
    div[data-testid="stVerticalBlock"] > div:has(.control-card),
    div[data-testid="stVerticalBlock"] > div:has(.recommendation-card),
    div[data-testid="stVerticalBlock"] > div:has(.section-shell) {
        margin-bottom: 0.35rem;
    }

    .hero-card {
        position: relative;
        overflow: hidden;
        border-radius: 30px;
        padding: 34px 34px 30px 34px;
        border: 1px solid rgba(216, 188, 123, 0.32);
        background:
            linear-gradient(135deg, rgba(17, 38, 65, 0.96), rgba(10, 19, 33, 0.88)),
            radial-gradient(circle at 80% 10%, rgba(216, 188, 123, 0.23), transparent 18rem);
        box-shadow: 0 22px 70px rgba(0, 0, 0, 0.33);
    }

    .hero-card:after {
        content: "";
        position: absolute;
        inset: auto -80px -120px auto;
        width: 360px;
        height: 360px;
        background: radial-gradient(circle, rgba(90, 169, 255, 0.18), transparent 60%);
        transform: rotate(20deg);
    }

    .hero-grid {
        position: relative;
        z-index: 1;
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 24px;
    }

    .hero-card h1 {
        margin: 0;
        font-size: clamp(2.2rem, 5vw, 4.8rem);
        line-height: 0.92;
        color: #fffaf0;
    }

    .hero-card p {
        max-width: 720px;
        margin: 16px 0 0 0;
        color: var(--park-text-muted);
        font-size: 1.08rem;
        line-height: 1.55;
    }

    .eyebrow {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 12px;
        color: var(--park-gold);
        font-size: 0.76rem;
        font-weight: 800;
        letter-spacing: 0.14em;
        text-transform: uppercase;
    }

    .hero-pill,
    .small-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        border: 1px solid rgba(216, 188, 123, 0.38);
        border-radius: 999px;
        padding: 7px 12px;
        font-size: 0.78rem;
        font-weight: 800;
        color: #fff7df;
        background: rgba(216, 188, 123, 0.12);
        white-space: nowrap;
    }

    .control-card,
    .section-shell,
    .chart-card,
    .recommendation-card {
        border: 1px solid var(--park-border);
        border-radius: 24px;
        background: var(--park-card);
        box-shadow: 0 15px 45px rgba(0, 0, 0, 0.22);
        backdrop-filter: blur(8px);
    }

    .control-card {
        padding: 18px 20px 6px 20px;
        margin-top: 18px;
    }

    .section-shell {
        padding: 22px 24px;
        margin: 26px 0 16px 0;
    }

    .compact-section {
        padding: 18px 22px;
    }

    .section-title {
        margin: 0;
        font-size: 1.75rem;
        color: #fffaf0;
    }

    .section-note {
        margin-top: 7px;
        margin-bottom: 0;
        color: var(--park-text-muted);
        font-size: 0.98rem;
        line-height: 1.45;
    }

    .recommendation-card {
        padding: 26px 28px;
        margin: 10px 0 18px 0;
        border-color: var(--park-border-strong);
        background:
            linear-gradient(135deg, rgba(29, 54, 84, 0.92), rgba(15, 29, 48, 0.86)),
            radial-gradient(circle at 85% 10%, rgba(216, 188, 123, 0.20), transparent 16rem);
    }

    .recommendation-card h2 {
        margin: 0 0 10px 0;
        font-size: clamp(1.8rem, 3vw, 3rem);
        color: #fffaf0;
    }

    .recommendation-card p {
        margin: 0;
        color: var(--park-text-muted);
        font-size: 1.02rem;
        line-height: 1.55;
    }

    .move-row {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
        margin-top: 18px;
    }

    .move-stat {
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 18px;
        padding: 14px;
        background: rgba(255, 255, 255, 0.055);
    }

    .move-label {
        color: var(--park-text-muted);
        font-size: 0.78rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }

    .move-value {
        margin-top: 4px;
        color: #ffffff;
        font-size: 1.35rem;
        font-weight: 800;
    }

    .chart-card {
        padding: 20px;
        margin-bottom: 24px;
    }

    div[data-testid="stMetric"] {
        background: rgba(13, 29, 49, 0.76);
        border: 1px solid rgba(165, 190, 220, 0.24);
        padding: 15px 17px;
        border-radius: 20px;
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.18);
    }

    div[data-testid="stMetricLabel"] {
        font-weight: 800;
        opacity: 0.84;
    }

    div[data-testid="stDataFrame"] {
        border-radius: 18px;
        overflow: hidden;
        border: 1px solid rgba(165, 190, 220, 0.22);
    }

    div[data-testid="stTabs"] button {
        border-radius: 999px !important;
        padding-left: 16px !important;
        padding-right: 16px !important;
    }

    .stButton > button {
        border-radius: 999px;
        border: 1px solid rgba(216, 188, 123, 0.55);
        background: linear-gradient(135deg, #1e5f94, #0f4c81);
        color: white;
        font-weight: 800;
        padding: 0.52rem 1.05rem;
        box-shadow: 0 10px 22px rgba(15, 76, 129, 0.28);
    }

    .stButton > button:hover {
        background: linear-gradient(135deg, #2678b9, #1769aa);
        border-color: rgba(216, 188, 123, 0.9);
        color: white;
    }

    @media (max-width: 760px) {
        .hero-grid,
        .move-row {
            display: block;
        }
        .hero-pill,
        .move-stat {
            margin-top: 12px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero-card">
        <div class="hero-grid">
            <div>
                <div class="eyebrow">✦ Live park intelligence</div>
                <h1>Epic Universe Day Planner</h1>
                <p>Live waits, historical patterns, and simple ride timing signals for the day.</p>
            </div>
            <div class="hero-pill">🎢 Guest Planner</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# Manual refresh
# -----------------------------
refresh_col, spacer_col = st.columns([1, 5])
with refresh_col:
    if st.button("↻ Refresh data"):
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


def create_or_restart_alert(
    ride_id,
    ride_name,
    current_wait_time,
    alert_mode,
    target_wait_time=None,
):
    now = pd.Timestamp.now(tz=EASTERN_TZ)
    today = now.date().isoformat()

    try:
        current_wait_time = float(current_wait_time)
    except Exception:
        current_wait_time = None

    if target_wait_time is not None:
        try:
            target_wait_time = float(target_wait_time)
        except Exception:
            target_wait_time = None

    if alert_mode == "Wait is X minutes or less":
        alert_type = "target_wait_time"
        threshold_base = "user_target_wait"
        threshold_mode = "target"
    else:
        alert_type = "optimal_from_request_wait"
        threshold_base = "request_wait_time"
        threshold_mode = "adaptive"

    alerts = load_alerts_from_s3()

    existing = None
    for alert in alerts:
        if alert.get("ride_id") == ride_id:
            existing = alert
            break

    threshold_fields = {
        "threshold_mode": threshold_mode,
        "threshold_percent_below_avg": 0.25,
        "threshold_min_minutes": 8,
        "threshold_max_minutes": 25,
        "threshold_base": threshold_base,
    }

    base_payload = {
        "ride_id": int(ride_id),
        "ride_name": ride_name,
        "alert_type": alert_type,
        **threshold_fields,
        "request_wait_time": current_wait_time,
        "target_wait_time": target_wait_time,
        "created_at_eastern": now.isoformat(),
        "created_date_eastern": today,
        "expires_date_eastern": today,
        "status": "active",
        "triggered_at_eastern": None,
        "last_checked_at_eastern": None,
        "cancelled_at_eastern": None,
    }

    if existing:
        existing_date = existing.get("created_date_eastern")
        existing_status = existing.get("status")

        if existing_date == today and existing_status == "active":
            return "already_active"

        existing.update(base_payload)
        save_alerts_to_s3(alerts)
        return "restarted"

    alerts.append(base_payload)
    save_alerts_to_s3(alerts)

    return "created"


def cancel_alert(ride_id):
    now = pd.Timestamp.now(tz=EASTERN_TZ)
    alerts = load_alerts_from_s3()

    changed = False

    for alert in alerts:
        if alert.get("ride_id") == ride_id and alert.get("status") == "active":
            alert["status"] = "cancelled"
            alert["cancelled_at_eastern"] = now.isoformat()
            changed = True
            break

    if changed:
        save_alerts_to_s3(alerts)
        return "cancelled"

    return "not_found"


# -----------------------------
# Formatting helpers
# -----------------------------
def format_alert_time(value):
    if not value:
        return "—"

    try:
        ts = pd.to_datetime(value, utc=True).tz_convert(EASTERN_TZ)
        return ts.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return "—"


def status_badge(status):
    status = str(status or "unknown").lower()

    mapping = {
        "active": "🟢 Active",
        "triggered": "✅ Triggered",
        "cancelled": "⚫ Cancelled",
        "expired": "⏳ Expired",
        "unknown": "❔ Unknown",
    }

    return mapping.get(status, f"❔ {status.title()}")


def rec_badge(rec):
    mapping = {
        "Great time": "✅ Great time",
        "Ride now": "🎯 Ride now",
        "Normal": "🟡 Normal",
        "Maybe wait": "🕒 Maybe wait",
        "Wait": "🔴 Wait",
        "Closed": "⚫ Closed",
        "Need history": "📊 Need history",
    }

    return mapping.get(rec, rec)


def friendly_alert_mode(alert):
    threshold_base = alert.get("threshold_base")
    alert_type = alert.get("alert_type")

    if threshold_base == "user_target_wait" or alert_type == "target_wait_time":
        return "Target wait"

    if threshold_base == "request_wait_time" or alert_type == "optimal_from_request_wait":
        return "Drop from when checked"

    if threshold_base == "same_hour_average" or alert_type == "optimal_same_hour":
        return "Better than normal"

    return alert.get("threshold_mode", "unknown")


def build_alert_status_table(alerts):
    if not alerts:
        return pd.DataFrame()

    rows = []

    for alert in alerts:
        rows.append({
            "Ride": alert.get("ride_name", "Unknown"),
            "Status": status_badge(alert.get("status", "unknown")),
            "Mode": friendly_alert_mode(alert),
            "Target": (
                f"{alert.get('target_wait_time'):.0f} min"
                if isinstance(alert.get("target_wait_time"), (int, float))
                else "—"
            ),
            "Wait When Set": (
                f"{alert.get('request_wait_time'):.0f} min"
                if isinstance(alert.get("request_wait_time"), (int, float))
                else "—"
            ),
            "Created": format_alert_time(alert.get("created_at_eastern")),
            "Last Checked": format_alert_time(alert.get("last_checked_at_eastern")),
            "Triggered": format_alert_time(alert.get("triggered_at_eastern")),
            "Cancelled": format_alert_time(alert.get("cancelled_at_eastern")),
        })

    return pd.DataFrame(rows)


def get_latest_collector_timestamp(history_df):
    if history_df.empty or "s3_last_modified" not in history_df.columns:
        return "N/A"

    latest = pd.to_datetime(history_df["s3_last_modified"], utc=True, errors="coerce").max()

    if pd.isna(latest):
        return "N/A"

    return latest.tz_convert(EASTERN_TZ).strftime("%I:%M %p %Z").lstrip("0")


def get_latest_alert_checker_timestamp(alerts):
    timestamps = []

    for alert in alerts:
        value = alert.get("last_checked_at_eastern")
        if value:
            timestamps.append(value)

    if not timestamps:
        return "N/A"

    latest = pd.to_datetime(timestamps, utc=True, errors="coerce").max()

    if pd.isna(latest):
        return "N/A"

    return latest.tz_convert(EASTERN_TZ).strftime("%I:%M %p %Z").lstrip("0")


def format_hour(hour):
    hour = int(hour)
    suffix = "AM" if hour < 12 else "PM"
    hour_12 = hour % 12

    if hour_12 == 0:
        hour_12 = 12

    return f"{hour_12:02d}:00 {suffix}"


def is_inside_park_hours(timestamp_eastern):
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
# Park map overlay helpers
# -----------------------------
def image_to_base64(path):
    with open(path, "rb") as file:
        return base64.b64encode(file.read()).decode("utf-8")


def get_map_image_path():
    if os.path.exists(MAP_IMAGE_PATH):
        return MAP_IMAGE_PATH

    if os.path.exists(MAP_IMAGE_FALLBACK_PATH):
        return MAP_IMAGE_FALLBACK_PATH

    return None


def normalize_ride_name(value):
    if pd.isna(value):
        return ""

    text = str(value)
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("’", "'")
    text = text.replace("‘", "'")
    text = text.replace("™", "")
    text = text.replace("®", "")
    text = text.replace(":", "")
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text)
    text = text.strip().lower()

    return text


def apply_map_ride_alias(value):
    """Normalize ride names into one canonical key for map/live-data matching."""
    ride_key = normalize_ride_name(value)

    aliases = {
        # Queue-Times appears to use singular "Hiccup Wing Glider";
        # the official map/PDF uses "Hiccup’s Wing Gliders".
        normalize_ride_name("Hiccup Wing Glider"): "hiccup_wing_glider",
        normalize_ride_name("Hiccup's Wing Glider"): "hiccup_wing_glider",
        normalize_ride_name("Hiccup’s Wing Glider"): "hiccup_wing_glider",
        normalize_ride_name("Hiccup's Wing Gliders"): "hiccup_wing_glider",
        normalize_ride_name("Hiccup’s Wing Gliders"): "hiccup_wing_glider",

        normalize_ride_name("Dragon Racer's Rally"): "dragon_racers_rally",
        normalize_ride_name("Dragon Racer’s Rally"): "dragon_racers_rally",

        normalize_ride_name("Mario Kart™: Bowser's Challenge"): "mario_kart_bowsers_challenge",
        normalize_ride_name("Mario Kart™: Bowser’s Challenge"): "mario_kart_bowsers_challenge",
        normalize_ride_name("Mario Kart: Bowser's Challenge"): "mario_kart_bowsers_challenge",
        normalize_ride_name("Mario Kart: Bowser’s Challenge"): "mario_kart_bowsers_challenge",

        normalize_ride_name("Yoshi's Adventure™"): "yoshis_adventure",
        normalize_ride_name("Yoshi’s Adventure™"): "yoshis_adventure",
        normalize_ride_name("Yoshi's Adventure"): "yoshis_adventure",
        normalize_ride_name("Yoshi’s Adventure"): "yoshis_adventure",
    }

    return aliases.get(ride_key, ride_key)


def get_wait_marker_style(wait_time, is_open):
    if pd.isna(is_open):
        return {"label": "?", "background": "#6b7280", "text": "#ffffff", "border": "#ffffff"}

    if is_open is False or is_open == False:
        return {"label": "X", "background": "#111827", "text": "#ffffff", "border": "#ffffff"}

    if pd.isna(wait_time):
        return {"label": "?", "background": "#6b7280", "text": "#ffffff", "border": "#ffffff"}

    wait_time = int(wait_time)

    if wait_time <= 20:
        return {"label": str(wait_time), "background": "#16a34a", "text": "#ffffff", "border": "#ffffff"}

    if wait_time <= 45:
        return {"label": str(wait_time), "background": "#eab308", "text": "#111827", "border": "#ffffff"}

    return {"label": str(wait_time), "background": "#dc2626", "text": "#ffffff", "border": "#ffffff"}


def build_wait_map_df(live_df):
    overlay_df = pd.DataFrame(OVERLAY_POINTS).copy()
    overlay_df["ride_key"] = overlay_df["attraction"].apply(apply_map_ride_alias)

    live_map = live_df.copy()
    live_map["ride_key"] = live_map["ride_name"].apply(apply_map_ride_alias)

    live_cols = [
        "ride_key",
        "ride_id",
        "ride_name",
        "land_name",
        "wait_time",
        "is_open",
        "last_updated_eastern",
    ]

    return overlay_df.merge(live_map[live_cols], on="ride_key", how="left")


def render_wait_time_overlay_map(map_df, map_zoom=100):
    image_path = get_map_image_path()

    if image_path is None:
        st.warning(
            "Map image not found. Add epic_universe_map_overlay_base.png to an assets folder "
            "or place it next to this app file."
        )
        return

    try:
        map_zoom = int(map_zoom)
    except Exception:
        map_zoom = 100

    map_zoom = max(80, min(map_zoom, 160))

    image_b64 = image_to_base64(image_path)
    marker_html = []

    for _, row in map_df.iterrows():
        style = get_wait_marker_style(row.get("wait_time"), row.get("is_open"))

        display_name = row.get("ride_name")
        if pd.isna(display_name) or not display_name:
            display_name = row.get("attraction", "Unknown attraction")

        if row.get("is_open") is False or row.get("is_open") == False:
            wait_label = "Closed"
        elif pd.notna(row.get("wait_time")):
            wait_label = f"{int(row.get('wait_time'))} min"
        else:
            wait_label = "No live data match"

        tooltip = html.escape(f"{display_name} | {wait_label}")
        x_pct = float(row["x_pct"])
        y_pct = float(row["y_pct"])

        safe_name = html.escape(str(display_name), quote=True)
        safe_wait_label = html.escape(str(wait_label), quote=True)

        land_value = row.get("land_name")
        if pd.isna(land_value) or not land_value:
            land_value = row.get("land", "")

        safe_land = html.escape(str(land_value), quote=True)

        marker_html.append(
            f"""
            <button
                type="button"
                class="wait-map-marker"
                title="{tooltip}"
                aria-label="{tooltip}"
                data-ride-name="{safe_name}"
                data-wait-label="{safe_wait_label}"
                data-land="{safe_land}"
                onclick="selectRideFromMap(this)"
                style="
                    left:{x_pct}%;
                    top:{y_pct}%;
                    background:{style['background']};
                    color:{style['text']};
                    border-color:{style['border']};
                "
            >
                {style['label']}
            </button>
            """
        )

    map_html = f"""
    <style>
        .wait-map-zoom-shell {{
            width: 100%;
            overflow-x: auto;
            overflow-y: hidden;
            padding: 0 0 10px 0;
            margin-bottom: 0.35rem;
        }}

        .wait-map-wrap {{
            position: relative;
            width: {map_zoom}%;
            min-width: 320px;
            max-width: none;
            margin: 0 auto 1.2rem auto;
            border-radius: 22px;
            overflow: hidden;
            border: 1px solid rgba(148, 163, 184, 0.35);
            box-shadow: 0 16px 36px rgba(15, 23, 42, 0.18);
            background: rgba(15, 23, 42, 0.04);
        }}

        .wait-map-wrap img {{
            width: 100%;
            display: block;
        }}

        .wait-map-marker {{
            position: absolute;
            transform: translate(-50%, -50%);
            min-width: 34px;
            height: 34px;
            padding: 0 8px;
            border-radius: 999px;
            border: 2px solid white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            font-size: 13px;
            line-height: 1;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
            z-index: 5;
            cursor: pointer;
            user-select: none;
            transition: transform 120ms ease, box-shadow 120ms ease, outline 120ms ease;
            appearance: none;
            -webkit-appearance: none;
        }}

        .wait-map-marker:hover,
        .wait-map-marker:focus,
        .wait-map-marker.active {{
            transform: translate(-50%, -50%) scale(1.14);
            box-shadow: 0 8px 22px rgba(0, 0, 0, 0.42);
            outline: 3px solid rgba(255, 255, 255, 0.72);
            outline-offset: 2px;
            z-index: 10;
        }}

        @media (max-width: 760px) {{
            .wait-map-marker {{
                min-width: 38px;
                height: 38px;
                font-size: 13px;
            }}
        }}

                .wait-map-legend {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            align-items: center;
            justify-content: center;
            margin-top: 0.35rem;
            margin-bottom: 0.55rem;
            font-size: 0.86rem;
            color: #f8fafc;
        }}

        .legend-pill {{
            display: inline-flex;
            align-items: center;
            gap: 7px;
            padding: 7px 12px;
            border-radius: 999px;
            border: 1px solid rgba(226, 232, 240, 0.42);
            background: rgba(15, 23, 42, 0.92);
            color: #f8fafc;
            font-weight: 700;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.22);
        }}

        .legend-dot {{
            width: 12px;
            height: 12px;
            border-radius: 999px;
            display: inline-block;
            border: 1px solid rgba(255, 255, 255, 0.65);
            flex: 0 0 auto;
        }}

        .selected-ride-card {{
            max-width: 720px;
            margin: 0.75rem auto 0 auto;
            padding: 14px 18px;
            border-radius: 18px;
            border: 1px solid rgba(226, 232, 240, 0.28);
            background: rgba(15, 23, 42, 0.92);
            color: #f8fafc;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
            text-align: center;
        }}

        .selected-ride-kicker {{
            color: #d8bc7b;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 4px;
        }}

        .selected-ride-name {{
            font-size: 1.08rem;
            font-weight: 900;
            line-height: 1.25;
        }}

        .selected-ride-meta {{
            margin-top: 4px;
            color: rgba(248, 250, 252, 0.78);
            font-size: 0.92rem;
            font-weight: 650;
        }}
    </style>

    <div class="wait-map-zoom-shell">
        <div class="wait-map-wrap">
            <img src="data:image/png;base64,{image_b64}" />
            {''.join(marker_html)}
        </div>
    </div>

    <div class="wait-map-legend">
        <span class="legend-pill"><span class="legend-dot" style="background:#16a34a;"></span> 0–20 min</span>
        <span class="legend-pill"><span class="legend-dot" style="background:#eab308;"></span> 21–45 min</span>
        <span class="legend-pill"><span class="legend-dot" style="background:#dc2626;"></span> 46+ min</span>
        <span class="legend-pill"><span class="legend-dot" style="background:#111827;"></span> Closed</span>
        <span class="legend-pill"><span class="legend-dot" style="background:#6b7280;"></span> No data match</span>
    </div>

    <div style="
        text-align:center;
        font-size:0.80rem;
        margin-top:0.15rem;
        color:#f8fafc;
        background:rgba(15, 23, 42, 0.82);
        border:1px solid rgba(226, 232, 240, 0.22);
        border-radius:999px;
        padding:7px 12px;
        width:max-content;
        max-width:92%;
        margin-left:auto;
        margin-right:auto;
    ">
        X = currently closed · ? = map point did not match a live Queue-Times ride name
    </div>

    <div id="selected-ride-card" class="selected-ride-card">
        <div class="selected-ride-kicker">Tap a marker</div>
        <div class="selected-ride-name">Select a ride to see details</div>
        <div class="selected-ride-meta">Ride name and current wait will appear here.</div>
    </div>

    <script>
        function selectRideFromMap(el) {{
            const name = el.dataset.rideName || "Unknown ride";
            const wait = el.dataset.waitLabel || "No wait data";
            const land = el.dataset.land || "";

            document.querySelectorAll(".wait-map-marker").forEach(marker => {{
                marker.classList.remove("active");
            }});
            el.classList.add("active");

            const card = document.getElementById("selected-ride-card");
            if (card) {{
                const landText = land ? land + " · " : "";
                card.innerHTML = `
                    <div class="selected-ride-kicker">Selected ride</div>
                    <div class="selected-ride-name">${{name}}</div>
                    <div class="selected-ride-meta">${{landText}}${{wait}}</div>
                `;
                card.scrollIntoView({{ behavior: "smooth", block: "nearest" }});
            }}
        }}
    </script>
    """

    components.html(
        map_html,
        height=1040,
        scrolling=False,
    )



# -----------------------------
# Reusable UI sections
# -----------------------------
def render_section_header(title, note=None, eyebrow=None):
    if eyebrow:
        st.caption(eyebrow)

    st.markdown(f"## {title}")

    if note:
        st.caption(note)


def render_current_queue_table(live_filtered):
    render_section_header("Full Wait Board")

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
        ["land_name", "ride_name"],
        ascending=[True, True],
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
# Sidebar controls
# -----------------------------
lands = ["All"] + sorted(live_df["land_name"].dropna().unique().tolist())

st.sidebar.header("Plan your view")

selected_land = st.sidebar.selectbox("Park area", lands)

history_days = st.sidebar.slider(
    "History window",
    min_value=1,
    max_value=30,
    value=30,
)

hide_single_rider = st.sidebar.toggle("Hide single rider", value=True)

current_open_only = st.sidebar.toggle(
    "Open only",
    value=False,
)

map_zoom = st.sidebar.slider(
    "Map zoom",
    min_value=80,
    max_value=160,
    value=100,
    step=10,
    help="100% keeps the default map size. Higher values zoom in and allow horizontal panning.",
)


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
render_section_header("Park Pulse")

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


# -----------------------------
# Park map overlay
# -----------------------------
st.markdown("## Park Map")
wait_map_df = build_wait_map_df(live_df)
render_wait_time_overlay_map(wait_map_df, map_zoom=map_zoom)


# -----------------------------
# Load S3 history
# -----------------------------
try:
    history_df = load_s3_history(days_back=history_days)
except Exception as e:
    st.error("Could not load S3 history.")
    st.exception(e)
    render_current_queue_table(live_filtered)
    st.stop()

if history_df.empty:
    st.info("No historical S3 snapshots found yet. Let the Lambda collector run a few times.")
    render_current_queue_table(live_filtered)
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
    render_current_queue_table(live_filtered)
    st.stop()

st.caption(
    f"{len(history_filtered):,} usable historical rows · last {history_days} day(s)"
)


# -----------------------------
# Decision table
# -----------------------------
st.markdown("## Best Moves Right Now")

current_hour = pd.Timestamp.now(tz=EASTERN_TZ).hour
next_hour = (current_hour + 1) % 24

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

    same_hour_delta = best["difference_vs_same_hour"]
    same_hour_phrase = (
        f"{abs(same_hour_delta):.0f} minutes better than this hour usually looks"
        if same_hour_delta < 0
        else f"{same_hour_delta:.0f} minutes higher than this hour usually looks"
    )

    overall_delta_label = (
        f"{best['difference_vs_overall']:.0f} min"
        if pd.notna(best["difference_vs_overall"])
        else "N/A"
    )

    st.markdown(
        f"""
        <div class="recommendation-card">
            <div class="eyebrow">Best move right now</div>
            <h2>{best["ride_name"]}</h2>
            <p>Current wait is <b>{best['wait_time']:.0f} minutes</b>, which is <b>{same_hour_phrase}</b>. This is the ride I would surface first for a guest-planning view.</p>
            <div class="move-row">
                <div class="move-stat">
                    <div class="move-label">Current wait</div>
                    <div class="move-value">{best['wait_time']:.0f} min</div>
                </div>
                <div class="move-stat">
                    <div class="move-label">Vs hour avg</div>
                    <div class="move-value">{same_hour_delta:.0f} min</div>
                </div>
                <div class="move-stat">
                    <div class="move-label">Vs 30D avg</div>
                    <div class="move-value">{overall_delta_label}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info("No open rides have enough same-hour history for an opportunity score right now.")

decision_table = comparison[[
    "land_name",
    "ride_name",
    "is_open",
    "wait_time",
    "same_hour_avg",
    "overall_avg_wait",
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

decision_table["recommendation"] = decision_table["recommendation"].apply(rec_badge)

decision_table = decision_table.sort_values(
    ["land_name", "ride_name"],
    ascending=[True, True],
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
render_section_header("Smart Ride Alert")

all_alerts = load_alerts_from_s3()
today = pd.Timestamp.now(tz=EASTERN_TZ).date().isoformat()

current_alerts = [
    alert for alert in all_alerts
    if alert.get("created_date_eastern") == today
]

status_col1, status_col2 = st.columns(2)
status_col1.metric("Last Collector Run", get_latest_collector_timestamp(history_df))
status_col2.metric("Last Alert Check", get_latest_alert_checker_timestamp(current_alerts))

alert_status_df = build_alert_status_table(current_alerts)

if not alert_status_df.empty:
    st.markdown("**Today’s alert watches**")
    st.dataframe(alert_status_df, use_container_width=True, hide_index=True)
else:
    st.info("No alert watches have been created yet.")

alert_ride_options = (
    comparison_base[
        (comparison_base["is_open"] == True) &
        (~comparison_base["is_single_rider"])
    ][["ride_id", "ride_name", "land_name", "wait_time"]]
    .drop_duplicates()
    .sort_values(["land_name", "ride_name"], ascending=[True, True])
)

if alert_ride_options.empty:
    st.info("No open rides available for new alerts right now.")
else:
    alert_labels = {
        f"{row['land_name']} — {row['ride_name']}": {
            "ride_id": row["ride_id"],
            "ride_name": row["ride_name"],
            "land_name": row["land_name"],
            "wait_time": row["wait_time"],
        }
        for _, row in alert_ride_options.iterrows()
    }

    selected_alert_label = st.selectbox(
        "Ride to watch",
        list(alert_labels.keys()),
        key="alert_ride_select",
    )

    selected_alert = alert_labels[selected_alert_label]

    alert_mode = st.radio(
        "Notify me when...",
        [
            "Wait is X minutes or less",
            "Wait drops meaningfully from when I checked",
        ],
        index=0,
        horizontal=False,
        key="alert_mode",
    )

    target_wait_time = None

    if alert_mode == "Wait is X minutes or less":
        current_wait_for_default = selected_alert.get("wait_time")

        if pd.notna(current_wait_for_default):
            default_target = max(5, int(current_wait_for_default) - 10)
        else:
            default_target = 30

        target_wait_time = st.slider(
            "Target wait time",
            min_value=5,
            max_value=120,
            value=min(default_target, 120),
            step=5,
            help="You will get one alert today if this ride reaches this wait time or lower.",
        )

        st.caption(
            f"Alert me when **{selected_alert['ride_name']}** is "
            f"**{target_wait_time} minutes or less**."
        )
    else:
        current_wait_for_caption = selected_alert.get("wait_time")

        if pd.notna(current_wait_for_caption):
            st.caption(
                f"Alert me when **{selected_alert['ride_name']}** drops meaningfully "
                f"below the current **{int(current_wait_for_caption)} min** wait."
            )
        else:
            st.caption(
                f"Alert me when **{selected_alert['ride_name']}** drops meaningfully "
                "below the wait shown when I checked."
            )

    if st.button("Notify When Optimal", key="notify_when_optimal"):
        try:
            result = create_or_restart_alert(
                selected_alert["ride_id"],
                selected_alert["ride_name"],
                selected_alert["wait_time"],
                alert_mode,
                target_wait_time,
            )

            if result == "already_active":
                st.warning(
                    "This ride already has an active watch today. "
                    "Cancel the active watch first if you want to switch alert modes."
                )
            else:
                if result == "restarted":
                    st.success("Restarted watch for today.")
                else:
                    st.success("Alert successful! I’ll notify you if it becomes optimal.")

                st.cache_data.clear()
                st.rerun()

        except Exception as e:
            st.error("Could not save alert rule to S3.")
            st.exception(e)

active_alerts = [
    alert for alert in current_alerts
    if alert.get("status") == "active"
]

if active_alerts:
    st.markdown("**Cancel a watch**")

    cancel_labels = {
        alert.get("ride_name", f"Ride {alert.get('ride_id')}"): alert.get("ride_id")
        for alert in active_alerts
    }

    selected_cancel_label = st.selectbox(
        "Active watch to cancel",
        list(cancel_labels.keys()),
        key="cancel_alert_select",
    )

    if st.button("Cancel Watch", key="cancel_watch"):
        result = cancel_alert(cancel_labels[selected_cancel_label])

        if result == "cancelled":
            st.success("Watch cancelled.")
            st.cache_data.clear()
            st.rerun()
        else:
            st.info("No active watch found to cancel.")



# -----------------------------
# Current queue table moved lower
# -----------------------------
render_current_queue_table(live_filtered)



# -----------------------------
# Historical insight charts in tabs
# -----------------------------
render_section_header("Crowd Patterns")

tab_heatmap, tab_profile, tab_daily, tab_weekday = st.tabs([
    "🔥 Heat Map",
    "📈 Ride Profile",
    "📊 Daily Average",
    "📅 Weekday",
])


with tab_daily:
    st.subheader("📊 Daily Average Wait")
    st.caption("Daily average wait from usable snapshots.")

    daily_avg = (
        history_filtered
        .groupby("collection_date_eastern", as_index=False)
        .agg(avg_wait=("wait_time", "mean"))
        .sort_values("collection_date_eastern")
    )

    daily_avg["collection_date_eastern"] = pd.to_datetime(daily_avg["collection_date_eastern"])
    daily_avg["date_label"] = daily_avg["collection_date_eastern"].dt.strftime("%a %m/%d")
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
            x=alt.X("date_label:N", title="Date", sort=None),
            y=alt.Y("avg_wait:Q", title="Wait Time (minutes)"),
            color=alt.Color(
                "avg_wait:Q",
                scale=alt.Scale(scheme="redyellowgreen", reverse=True),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("date_label:N", title="Date"),
                alt.Tooltip("avg_wait:Q", title="Avg Wait", format=".1f"),
            ],
        )
    )

    rolling = (
        alt.Chart(daily_avg)
        .mark_line(color="#555555", strokeWidth=3)
        .encode(
            x=alt.X("date_label:N", title="Date", sort=None),
            y="rolling_avg:Q",
            tooltip=[
                alt.Tooltip("date_label:N", title="Date"),
                alt.Tooltip("rolling_avg:Q", title="Rolling Avg", format=".1f"),
            ],
        )
    )

    st.altair_chart((bars + rolling).properties(height=380), use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)


with tab_heatmap:
    st.subheader("🔥 Hourly Heat Map")
    st.caption("Average wait by ride and hour.")

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


with tab_profile:
    st.subheader("📈 Ride Profile")
    st.caption("Selected day vs typical hourly pattern.")

    ride_profile_options = (
        history_filtered[["ride_id", "ride_name", "land_name"]]
        .dropna(subset=["ride_name", "land_name"])
        .drop_duplicates()
        .sort_values(["land_name", "ride_name"], ascending=[True, True])
    )

    ride_profile_labels = {
        f"{row['land_name']} — {row['ride_name']}": {
            "ride_id": row["ride_id"],
            "ride_name": row["ride_name"],
            "land_name": row["land_name"],
        }
        for _, row in ride_profile_options.iterrows()
    }

    selected_ride_label = st.selectbox(
        "Select ride",
        list(ride_profile_labels.keys()),
        key="selected_ride_profile",
    )

    selected_ride_info = ride_profile_labels[selected_ride_label]
    selected_ride = selected_ride_info["ride_name"]
    selected_ride_id = selected_ride_info["ride_id"]

    available_dates = sorted(history_filtered["collection_date_eastern"].dropna().unique().tolist())

    selected_date = st.selectbox(
        "Selected date for posted wait points",
        available_dates,
        index=len(available_dates) - 1,
        key="selected_profile_date",
    )

    ride_history = history_filtered[history_filtered["ride_id"] == selected_ride_id].copy()

    typical_wait = (
        ride_history
        .groupby("collection_hour_eastern", as_index=False)
        .agg(typical_wait=("wait_time", "mean"))
        .sort_values("collection_hour_eastern")
    )

    selected_day_points = ride_history[
        ride_history["collection_date_eastern"] == selected_date
    ].copy()

    selected_day_points["time_of_day"] = (
        selected_day_points["collected_at_eastern"].dt.tz_localize(None)
    )

    base_date = pd.to_datetime(selected_date)

    typical_wait["time_of_day"] = typical_wait["collection_hour_eastern"].apply(
        lambda h: base_date + pd.Timedelta(hours=int(h))
    )

    selected_date_label = pd.to_datetime(selected_date).strftime("%m/%d/%Y")

    chart_max_wait = pd.concat([
        typical_wait["typical_wait"],
        selected_day_points["wait_time"],
    ]).max()

    if pd.notna(chart_max_wait):
        y_axis_max = max(20, int(((chart_max_wait * 1.15) + 9) // 10 * 10))
    else:
        y_axis_max = 120

    wait_y_axis = alt.Y(
        "typical_wait:Q",
        title="Wait Time (minutes)",
        scale=alt.Scale(domain=[0, y_axis_max]),
    )

    posted_wait_y_axis = alt.Y(
        "wait_time:Q",
        title="Wait Time (minutes)",
        scale=alt.Scale(domain=[0, y_axis_max]),
    )

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
            y=wait_y_axis,
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
            y=posted_wait_y_axis,
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
            y=posted_wait_y_axis,
        )
    )

    st.altair_chart(
        (typical_line + posted_line + posted_points).properties(height=400),
        use_container_width=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)


with tab_weekday:
    st.subheader("📅 Average Wait by Weekday")
    st.caption("Average wait by weekday.")

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