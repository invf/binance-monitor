import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode='require')
cur = conn.cursor()

def init_db():
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id SERIAL PRIMARY KEY,
            symbol TEXT,
            timestamp TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()

def save_signal(symbol):
    cur.execute("INSERT INTO signals (symbol) VALUES (%s)", (symbol,))
    conn.commit()

def check_repeats(symbol):
    cur.execute("""
        SELECT COUNT(*) FROM (
            SELECT * FROM signals
            WHERE symbol = %s
            ORDER BY timestamp DESC
            LIMIT 3
        ) AS recent
    """, (symbol,))
    count = cur.fetchone()[0]
    return count == 3
