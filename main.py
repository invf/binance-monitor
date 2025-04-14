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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()]
)

print("🚀 Binance + Telegram bot is starting...")

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
MONITOR_DURATION = 2 * 60 * 60  # 2 hours

signal_triggered = set()


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

def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        logging.error(f"Telegram Error: {e}")

def monitor_symbol(symbol):
    end_time = time.time() + MONITOR_DURATION
    while time.time() < end_time:
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

            if all([
                price_15m < -PRICE_DROP_THRESHOLD,
                price_30m < -PRICE_DROP_THRESHOLD,
                price_1h < 0,
                price_4h < 0,
                (volume_1h is not None and volume_1h < 0),
                (volume_4h is not None and volume_4h < 0),
            ]):
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

"""
                send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg.strip())
                break
        except Exception as e:
            logging.error(f"[Monitoring Error] {symbol}: {e}")
        time.sleep(CHECK_INTERVAL)

def check_all():
    for symbol in SYMBOLS:
        try:
            if symbol in signal_triggered:
                continue
            k_15m = get_klines(symbol, KLINE_INTERVAL_15MINUTE)
            k_1h = get_klines(symbol, KLINE_INTERVAL_1HOUR)

            rsi_15m = calculate_rsi(k_15m)
            rsi_1h = calculate_rsi(k_1h)

            if rsi_15m > RSI_15M_THRESHOLD and rsi_1h > RSI_1H_THRESHOLD:
                signal_triggered.add(symbol)
                threading.Thread(target=monitor_symbol, args=(symbol,), daemon=True).start()
                logging.info(f"🎯 Triggered RSI check: {symbol} | RSI(15m): {rsi_15m} | RSI(1h): {rsi_1h}")
        except Exception as e:
            logging.error(f"[Check Error] {symbol}: {e}")

def main_loop():
    while True:
        if STARTED:
            check_all()
        time.sleep(CHECK_INTERVAL)

threading.Thread(target=main_loop, daemon=True).start()

while True:
    time.sleep(10)
