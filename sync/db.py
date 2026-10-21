import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "garmin.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    activity_id INTEGER PRIMARY KEY,
    name TEXT,
    activity_type TEXT,
    start_time TEXT,
    duration_sec REAL,
    distance_m REAL,
    calories REAL,
    avg_hr REAL,
    max_hr REAL,
    avg_speed_mps REAL,
    elevation_gain_m REAL,
    training_effect_aerobic REAL,
    training_effect_anaerobic REAL,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS splits (
    activity_id INTEGER PRIMARY KEY,
    splits_json TEXT
);

CREATE TABLE IF NOT EXISTS sleep (
    date TEXT PRIMARY KEY,
    total_sleep_sec INTEGER,
    deep_sec INTEGER,
    light_sec INTEGER,
    rem_sec INTEGER,
    awake_sec INTEGER,
    sleep_score INTEGER,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS daily_summary (
    date TEXT PRIMARY KEY,
    steps INTEGER,
    calories_total REAL,
    calories_active REAL,
    resting_hr INTEGER,
    avg_stress INTEGER,
    floors_climbed REAL,
    distance_m REAL,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS heart_rate_intraday (
    date TEXT,
    ts INTEGER,
    value INTEGER,
    PRIMARY KEY (date, ts)
);

CREATE TABLE IF NOT EXISTS stress_intraday (
    date TEXT,
    ts INTEGER,
    value INTEGER,
    PRIMARY KEY (date, ts)
);

CREATE TABLE IF NOT EXISTS body_battery_intraday (
    date TEXT,
    ts INTEGER,
    value INTEGER,
    PRIMARY KEY (date, ts)
);

CREATE TABLE IF NOT EXISTS sync_log (
    date TEXT,
    dataset TEXT,
    synced_at TEXT,
    PRIMARY KEY (date, dataset)
);
"""


def db_path(persona=None):
    """Perfil por defecto: data/garmin.db. Otra persona: data/<persona>/garmin.db"""
    return DB_PATH if not persona else DB_PATH.parent / persona / "garmin.db"


def get_conn(persona=None):
    path = db_path(persona)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA)
    return conn
