import time
import os
import json
import pandas as pd
from ta.momentum import RSIIndicator
from binance.client import Client
from binance.enums import KLINE_INTERVAL_15MINUTE, KLINE_INTERVAL_1HOUR, KLINE_INTERVAL_4HOUR
import requests
from collections import defaultdict
import logging
import threading

# === LOGGING SETUP (для Render) ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()]  # тільки вивід у консоль
)

print("🚀 Binance + Telegram bot is starting...")

# === LOAD ENV VARIABLES (через Render) ===
API_KEY = os.environ["BINANCE_API_KEY"]
API_SECRET = os.environ["BINANCE_SECRET"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

RSI_15M_THRESHOLD = 50
RSI_1H_THRESHOLD = 50
PRICE_DROP_THRESHOLD = 0.0
STARTED = False

client = Client(API_KEY, API_SECRET)

SYMBOLS = [s['symbol'] for s in client.get_all_tickers() if s['symbol'].endswith('USDT')]

LIMIT = 100
RSI_WINDOW = 14
CHECK_INTERVAL = 20

signal_counter = defaultdict(int)

def get_klines(symbol, interval):
    return client.get_klines(symbol=symbol, interval=interval, limit=LIMIT)

def calculate_price_change(klines, period):
    open_price = float(klines[-period][1])
    close_price = float(klines[-1][4])
    return round(((close_price - open_price) / open_price) * 100, 2)

def calculate_volume_change(klines, period):
    volume_start = float(klines[-period][5])
    volume_end = float(klines[-1][5])
    if volume_start == 0:
        return None
    return round(((volume_end - volume_start) / volume_start) * 100, 2)

def calculate_rsi(klines):
    closes = [float(k[4]) for k in klines]
    df = pd.DataFrame(closes, columns=["close"])
    rsi = RSIIndicator(close=df["close"], window=RSI_WINDOW).rsi()
    return round(rsi.iloc[-1], 2)

def send_telegram_message(token, chat_id, message, reply_markup=None):
    if not message:
        message = "\u2753 Unknown message"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": int(chat_id),
        "text": message
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Telegram error: {e} | Payload: {json.dumps(payload, ensure_ascii=False)}")

def telegram_listener():
    global RSI_15M_THRESHOLD, RSI_1H_THRESHOLD, PRICE_DROP_THRESHOLD, STARTED
    offset = None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "RSI < 40", "callback_data": "rsi_40"},
                {"text": "RSI < 50", "callback_data": "rsi_50"},
                {"text": "RSI < 60", "callback_data": "rsi_60"},
                {"text": "RSI < 70", "callback_data": "rsi_70"}
            ],
            [
                {"text": "Price Drop < -0.5%", "callback_data": "price_drop_0.5"},
                {"text": "Price Drop < -1%", "callback_data": "price_drop_1.0"}
            ],
            [
                {"text": "▶ Start", "callback_data": "start"},
                {"text": "🔁 Restart", "callback_data": "restart"}
            ]
        ]
    }

    send_telegram_message(
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_CHAT_ID,
        "👋 Welcome! Set RSI and price drop thresholds, then press ▶ Start.",
        reply_markup=json.dumps(reply_markup)
    )

    while True:
        try:
            response = requests.get(url, params={"offset": offset, "timeout": 60})
            data = response.json()

            for update in data.get("result", []):
                offset = update["update_id"] + 1

                if "message" in update:
                    msg_chat = update["message"].get("chat")
                    msg = update["message"].get("text", "")
                    if msg == "/settings" and msg_chat:
                        message = f"📊 <b>Current Thresholds</b>\n• RSI 15m: < {RSI_15M_THRESHOLD}\n• RSI 1h: < {RSI_1H_THRESHOLD}\n• Price Drop: < -{PRICE_DROP_THRESHOLD}%\n\nClick ▶ Start to run."
                        send_telegram_message(TELEGRAM_BOT_TOKEN, msg_chat.get("id"), message)

                elif "callback_query" in update:
                    callback = update["callback_query"]
                    callback_data = callback.get("data")
                    chat_id = callback.get("message", {}).get("chat", {}).get("id")

                    if callback_data and chat_id:
                        if callback_data.startswith("rsi_"):
                            val = int(callback_data.split("_")[1])
                            RSI_15M_THRESHOLD = val
                            RSI_1H_THRESHOLD = val
                            send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id, f"✅ RSI thresholds updated to < {val}")
                        elif callback_data.startswith("price_drop_"):
                            val = float(callback_data.split("_")[2])
                            PRICE_DROP_THRESHOLD = val
                            send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id, f"✅ Price drop threshold updated to < -{val}%")
                        elif callback_data == "start":
                            STARTED = True
                            send_telegram_message(
                                TELEGRAM_BOT_TOKEN,
                                chat_id,
                                f"✅ Monitoring started...\nRSI thresholds: 15m < {RSI_15M_THRESHOLD}, 1h < {RSI_1H_THRESHOLD}\nPrice Drop < -{PRICE_DROP_THRESHOLD}%"
                            )
                        elif callback_data == "restart":
                            STARTED = False
                            time.sleep(1)
                            STARTED = True
                            send_telegram_message(
                                TELEGRAM_BOT_TOKEN,
                                chat_id,
                                f"🔁 Monitoring restarted...\nRSI thresholds: 15m < {RSI_15M_THRESHOLD}, 1h < {RSI_1H_THRESHOLD}\nPrice Drop < -{PRICE_DROP_THRESHOLD}%"
                            )

        except Exception as e:
            logging.error(f"[Telegram Listener] Error: {e}")
            time.sleep(5)

def check_all():
    for symbol in SYMBOLS:
        try:
            k_15m = get_klines(symbol, KLINE_INTERVAL_15MINUTE)
            k_1h = get_klines(symbol, KLINE_INTERVAL_1HOUR)
            k_4h = get_klines(symbol, KLINE_INTERVAL_4HOUR)

            price_15m = calculate_price_change(k_15m, 15)
            price_30m = calculate_price_change(k_15m, 2)
            price_1h = calculate_price_change(k_1h, 1)
            price_4h = calculate_price_change(k_4h, 1)

            volume_1h = calculate_volume_change(k_1h, 2)
            volume_4h = calculate_volume_change(k_4h, 2)

            rsi_15m = calculate_rsi(k_15m)
            rsi_1h = calculate_rsi(k_1h)

            if all([
                price_15m < -PRICE_DROP_THRESHOLD,
                price_30m < -PRICE_DROP_THRESHOLD,
                price_1h < 0,
                price_4h < 0,
                (volume_1h is not None and volume_1h < 0),
                (volume_4h is not None and volume_4h < 0),
                rsi_15m < RSI_15M_THRESHOLD,
                rsi_1h < RSI_1H_THRESHOLD
            ]):
                signal_counter[symbol] += 1
            else:
                signal_counter[symbol] = 0

            if signal_counter[symbol] > 0:
                log_msg = f"{symbol} | Count: {signal_counter[symbol]} | Price(15m/30m/1h/4h): {price_15m}% / {price_30m}% / {price_1h}% / {price_4h}% | Volume(1h/4h): {volume_1h}% / {volume_4h}% | RSI(15m/1h): {rsi_15m} / {rsi_1h}"
                print(log_msg)
                logging.info(log_msg)

            if signal_counter[symbol] >= 3:
                msg = f"""
📊 {symbol}
📈 Зміна ціни:
  • 15м: {price_15m}%
  • 30м: {price_30m}%
  • 1г: {price_1h}%
  • 4г: {price_4h}%

💧 Зміна об'єму:
  • 1г: {volume_1h}%
  • 4г: {volume_4h}%

📉 RSI:
  • 15м: {rsi_15m} (threshold: <{RSI_15M_THRESHOLD})
  • 1г: {rsi_1h} (threshold: <{RSI_1H_THRESHOLD})
"""
                send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg.strip())
                signal_counter[symbol] = 0

        except Exception as e:
            error_msg = f"Помилка для {symbol}: {e}"
            print(error_msg)
            logging.error(error_msg)

# === START ===
threading.Thread(target=telegram_listener, daemon=True).start()

while True:
    if STARTED:
        check_all()
    time.sleep(CHECK_INTERVAL)
