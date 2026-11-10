import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Dawadmi city center (fixed location; not the phone's location)
LAT = 24.5070
LON = 44.3920
STATE_FILE = "hail_state.json"

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

URL = (
    "https://api.open-meteo.com/v1/forecast?"
    + urllib.parse.urlencode({
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,precipitation,rain,showers,snowfall,weather_code",
        "hourly": "precipitation_probability,precipitation,showers,weather_code,cape",
        "forecast_days": 2,
        "timezone": "Asia/Riyadh",
    })
)

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "DawadmiHailAlert/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
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
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_alert_key": None}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def main():
    data = get_json(URL)
    current = data.get("current", {})
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    codes = hourly.get("weather_code", [])
    probs = hourly.get("precipitation_probability", [])
    precip = hourly.get("precipitation", [])
    showers = hourly.get("showers", [])
    cape = hourly.get("cape", [])

    # WMO codes 95-99 indicate thunderstorm conditions; 96 and 99 include hail.
    # This is a forecast signal, NOT live radar or confirmation of hail at the site.
    candidates = []
    for i, time_text in enumerate(times):
        code = codes[i] if i < len(codes) else None
        probability = probs[i] if i < len(probs) else 0
        rain_mm = precip[i] if i < len(precip) else 0
        shower_mm = showers[i] if i < len(showers) else 0
        cape_value = cape[i] if i < len(cape) else 0

        if code in (96, 99):
            level = "RED"
            title = "🔴 إشارة توقعات تتضمن عاصفة رعدية مع بَرَد"
        elif code == 95:
            level = "ORANGE"
            title = "🟠 إشارة توقعات لعاصفة رعدية"
        elif (probability or 0) >= 60 and (cape_value or 0) >= 500 and ((rain_mm or 0) + (shower_mm or 0)) > 0:
            level = "YELLOW"
            title = "🟡 مؤشرات جوية قد تدعم تطور عواصف رعدية"
        else:
            continue

        candidates.append({
            "time": time_text,
            "level": level,
            "title": title,
            "probability": probability or 0,
            "cape": cape_value or 0,
            "code": code,
        })

    if not candidates:
        print("No qualifying thunderstorm/hail forecast signal.")
        return

    # Alert for the earliest forecast time only. Suppress repeats for that same signal.
    event = candidates[0]
    key = f'{event["time"]}:{event["level"]}:{event["code"]}'
    state = load_state()
    if state.get("last_alert_key") == key:
        print("Duplicate forecast signal; alert suppressed.")
        return

    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    message = (
        f"تنبيه طقس للدوادمي\n\n"
        f'{event["title"]}\n'
        f'وقت الفترة المتوقعة: {event["time"]} (توقيت الرياض)\n'
        f'احتمال الهطول المتوقع: {event["probability"]}%\n'
        f'CAPE: {event["cape"]} J/kg\n\n'
        f"الموقع: مركز الدوادمي\n"
        f"وقت الفحص: {now}\n\n"
        f"مهم: هذا تنبيه مبني على توقعات Open-Meteo، وليس رصد رادار مباشر. "
        f"لا يحدد موقع السحابة أو اتجاهها أو مسافة اقترابها، ولا يضمن تساقط البَرَد "
        f"أو مهلة إنذار 20 دقيقة. تحقق من تنبيهات المركز الوطني للأرصاد قبل اتخاذ القرار."
    )
    send_telegram(message)
    state["last_alert_key"] = key
    save_state(state)
    print("Alert sent:", key)

if __name__ == "__main__":
    main()
