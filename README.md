# Dawadmi Hail Alert (Prototype)

A free GitHub Actions prototype that checks Open-Meteo forecast data for the fixed center of Dawadmi and sends Telegram alerts when forecast signals meet simple thresholds.

## Important limitations

- This is **not** a live weather-radar tracker.
- It does not detect a storm cell's location, distance, speed, or direction.
- It cannot guarantee a 20-minute warning.
- WMO weather codes 96 and 99 describe thunderstorm forecasts with hail signals; they do not guarantee hail at the exact location.
- Yellow/orange/red are signal levels in this prototype, not calibrated probabilities of hail.
- Use official National Center for Meteorology alerts and local safety guidance for decisions.

## Setup

1. Create a Telegram bot using BotFather and obtain its token.
2. Obtain your Telegram chat ID.
3. In the GitHub repository, open **Settings → Secrets and variables → Actions**.
4. Add repository secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. Open **Actions**, enable workflows if GitHub asks, then run **Dawadmi Hail Alert** manually once using **Run workflow**.
6. Confirm that a test alert is received only if a qualifying forecast signal exists. This workflow does not send a test message automatically.

## Files

- `hail_alert.py`: forecast check and Telegram notification.
- `.github/workflows/hail_alert.yml`: scheduled run every five minutes.
- `hail_state.json`: duplicate-alert suppression state.

## Data source

Open-Meteo forecast API: https://open-meteo.com/

This prototype uses no paid API key. Review the provider's terms and availability before relying on it.
