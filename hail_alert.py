import json
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Fixed monitoring grid around Dawadmi (center + 8 surrounding points).
# These are forecast grid points, NOT radar storm-cell locations.
CENTER_LAT = 24.5070
CENTER_LON = 44.3920
OFFSET = 0.09  # approximately 10 km north/south; longitude spacing is similar here
POINTS = [
    ("مركز الدوادمي", CENTER_LAT, CENTER_LON),
    ("شمال الدوادمي", CENTER_LAT + OFFSET, CENTER_LON),
    ("جنوب الدوادمي", CENTER_LAT - OFFSET, CENTER_LON),
    ("شرق الدوادمي", CENTER_LAT, CENTER_LON + OFFSET),
    ("غرب الدوادمي", CENTER_LAT, CENTER_LON - OFFSET),
    ("شمال شرق الدوادمي", CENTER_LAT + OFFSET, CENTER_LON + OFFSET),
    ("شمال غرب الدوادمي", CENTER_LAT + OFFSET, CENTER_LON - OFFSET),
    ("جنوب شرق الدوادمي", CENTER_LAT - OFFSET, CENTER_LON + OFFSET),
    ("جنوب غرب الدوادمي", CENTER_LAT - OFFSET, CENTER_LON - OFFSET),
]

STATE_FILE = "hail_state.json"
LOCAL_TZ = ZoneInfo("Asia/Riyadh")
FORECAST_HOURS = 18
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

HOURLY_VARS = [
    "precipitation_probability", "precipitation", "rain", "showers",
    "weather_code", "cape", "thunderstorm_probability",
    "wind_speed_10m", "wind_gusts_10m", "wind_direction_10m",
    "temperature_2m", "freezing_level_height", "lifted_index",
    "convective_inhibition", "relative_humidity_2m",
]

def build_url():
    params = {
        "latitude": ",".join(f"{p[1]:.4f}" for p in POINTS),
        "longitude": ",".join(f"{p[2]:.4f}" for p in POINTS),
        "hourly": ",".join(HOURLY_VARS),
        "forecast_days": 2,
        "timezone": "Asia/Riyadh",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }
    return "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "DawadmiHailAlert/2.0"})
    with urllib.request.urlopen(req, timeout=35) as response:
        return json.loads(response.read().decode("utf-8"))

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=25) as response:
        result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API error: {result}")

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            return {"last_alerts": {}}
        return state
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_alerts": {}}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def value_at(hourly, key, index, default=None):
    values = hourly.get(key) or []
    return values[index] if index < len(values) else default

def safe_num(value, default=0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default

def direction_text(degrees):
    if degrees is None:
        return "غير متاح"
    names = ["شمال", "شمال شرقي", "شرق", "جنوب شرقي",
             "جنوب", "جنوب غربي", "غرب", "شمال غربي"]
    return names[int((float(degrees) % 360 + 22.5) // 45) % 8]

def assess(hourly, index, point_name):
    code = value_at(hourly, "weather_code", index)
    probability = safe_num(value_at(hourly, "precipitation_probability", index))
    rain = safe_num(value_at(hourly, "precipitation", index))
    showers = safe_num(value_at(hourly, "showers", index))
    cape = safe_num(value_at(hourly, "cape", index))
    storm_prob_raw = value_at(hourly, "thunderstorm_probability", index)
    storm_prob = safe_num(storm_prob_raw, -1)
    gust = safe_num(value_at(hourly, "wind_gusts_10m", index), -1)
    wind = safe_num(value_at(hourly, "wind_speed_10m", index), -1)
    wind_dir = value_at(hourly, "wind_direction_10m", index)
    freezing = value_at(hourly, "freezing_level_height", index)
    lifted = value_at(hourly, "lifted_index", index)
    cin = value_at(hourly, "convective_inhibition", index)
    temp = value_at(hourly, "temperature_2m", index)
    humidity = value_at(hourly, "relative_humidity_2m", index)

    # WMO 96/99 are forecast codes for thunderstorms with hail.
    # They are model signals, not confirmation of hail on the ground.
    hail_code = code in (96, 99)
    thunder_code = code == 95
    precip_present = (rain + showers) > 0.0

    if hail_code:
        level, title = 3, "🔴 إشارة توقعات قوية لعاصفة رعدية مصحوبة بالبَرَد"
    elif thunder_code or (storm_prob >= 60 and cape >= 700 and probability >= 50):
        level, title = 2, "🟠 مؤشرات قوية على عاصفة رعدية"
    elif (probability >= 50 and cape >= 400 and precip_present) or (storm_prob >= 35 and probability >= 40):
        level, title = 1, "🟡 مؤشرات جوية قد تدعم تطور عواصف رعدية"
    else:
        return None

    # A thunderstorm/hail code without any forecast precipitation is retained,
    # because the weather code itself is a relevant model signal.
    return {
        "level": level, "title": title, "point": point_name, "code": code,
        "probability": round(probability), "storm_probability": round(storm_prob) if storm_prob >= 0 else None,
        "cape": round(cape), "rain": rain, "showers": showers,
        "wind": wind, "gust": gust, "wind_direction": wind_dir,
        "freezing": freezing, "lifted": lifted, "cin": cin,
        "temperature": temp, "humidity": humidity,
    }

def fmt(value, suffix="", digits=0):
    if value is None:
        return "غير متاح"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "غير متاح"

def main():
    response = get_json(build_url())
    # Open-Meteo returns one object per coordinate when multiple coordinates are requested.
    datasets = response if isinstance(response, list) else [response]
    now = datetime.now(LOCAL_TZ).replace(minute=0, second=0, microsecond=0)
    end = now + timedelta(hours=FORECAST_HOURS)
    events = []

    for point_index, dataset in enumerate(datasets[:len(POINTS)]):
        hourly = dataset.get("hourly", {})
        times = hourly.get("time", [])
        for i, time_text in enumerate(times):
            try:
                event_time = datetime.fromisoformat(time_text).replace(tzinfo=LOCAL_TZ)
            except (TypeError, ValueError):
                continue
            if event_time < now or event_time > end:
                continue
            assessment = assess(hourly, i, POINTS[point_index][0])
            if assessment:
                assessment["time"] = event_time
                events.append(assessment)

    if not events:
        print(f"No qualifying forecast signal in next {FORECAST_HOURS} hours.")
        return

    # Group points by the same forecast hour; select the strongest signal.
    # Prioritize risk level, then the nearest forecast time.
    events.sort(key=lambda e: (-e["level"], e["time"]))
    event = events[0]
    same_hour = [e for e in events if e["time"] == event["time"]]
    strongest = max(same_hour, key=lambda e: e["level"])
    affected = list(dict.fromkeys(e["point"] for e in same_hour))
    event = strongest

    event_key = event["time"].strftime("%Y-%m-%dT%H:00")
    state = load_state()
    sent = state.get("last_alerts", {})
    if not isinstance(sent, dict):
        sent = {}

    previous_level = int(sent.get(event_key, 0) or 0)
    if previous_level >= event["level"]:
        print(f"Duplicate or lower-level alert suppressed: {event_key}")
        return

    remaining = max(0, int((event["time"] - now).total_seconds() // 60))
    if event["level"] == 3:
        recommendation = "انقل السيارة فوراً إلى مكان مسقوف إن أمكن، وتابع التنبيهات الرسمية."
    elif event["level"] == 2:
        recommendation = "استعد لإيقاف السيارة في مكان مسقوف إذا بدأت السحب الرعدية بالاقتراب."
    else:
        recommendation = "تابع تحديثات الطقس وجهّز مكاناً آمناً للسيارة احتياطاً."

    storm_line = (
        f'احتمال العواصف الرعدية: {event["storm_probability"]}%\n'
        if event["storm_probability"] is not None else
        "احتمال العواصف الرعدية: غير متاح من النموذج\n"
    )
    wind_line = (
        f'الرياح: {fmt(event["wind"], " كم/س")} | الهبات: {fmt(event["gust"], " كم/س")}\n'
        f'اتجاه الرياح: {direction_text(event["wind_direction"])}\n'
    )
    freezing_line = (
        f'ارتفاع مستوى التجمد: {fmt(event["freezing"], " م")}\n'
        if event["freezing"] is not None else ""
    )

    message = (
        "🌩️ تنبيه طقس للدوادمي\n\n"
        f'{event["title"]}\n'
        f'وقت الحالة المتوقع: {event["time"].strftime("%Y-%m-%d %H:%M")} (توقيت الرياض)\n'
        f'الوقت المتبقي حسب التوقع: نحو {remaining} دقيقة\n\n'
        "📍 نطاق المؤشرات:\n"
        + "، ".join(affected)
        + "\n\n"
        "📊 تفاصيل التوقع:\n"
        f'احتمال الهطول: {event["probability"]}%\n'
        + storm_line
        + f'CAPE: {fmt(event["cape"], " J/kg")}\n'
        + f'كمية الهطول المتوقعة: {fmt(event["rain"] + event["showers"], " ملم", 1)}\n'
        + wind_line
        + f'الرطوبة: {fmt(event["humidity"], "%")}\n'
        + f'درجة الحرارة: {fmt(event["temperature"], "°م", 1)}\n'
        + freezing_line
        + f'Lifted Index: {fmt(event["lifted"], "", 1)} | CIN: {fmt(event["cin"], " J/kg")}\n\n'
        "🚗 التوصية:\n"
        + recommendation
        + "\n\n"
        "⚠️ تنبيه علمي مهم:\n"
        "هذه قراءة توقعات عددية من Open-Meteo لعدة نقاط حول الدوادمي، وليست راداراً مباشراً. "
        "لا يمكن منها تحديد موقع خلية العاصفة الفعلي أو اتجاه حركتها أو سرعة اقترابها، "
        "ولا تمثل نسبة احتمال البَرَد. رمز الطقس 96/99 يشير إلى توقع عاصفة مع بَرَد "
        "ولا يثبت وصول البَرَد إلى الأرض. لا تعتمد على مهلة الوصول وحدها؛ تابع تنبيهات "
        "المركز الوطني للأرصاد والرصد المحلي."
    )

    send_telegram(message)
    sent[event_key] = event["level"]
    # Keep state compact (last 72 forecast-hour keys).
    for old_key in sorted(sent)[:-72]:
        sent.pop(old_key, None)
    state["last_alerts"] = sent
    state["last_alert_key"] = f'{event_key}:LEVEL_{event["level"]}'
    save_state(state)
    print(f'Alert sent: {event_key}, level={event["level"]}, points={len(affected)}')

if __name__ == "__main__":
    main()
