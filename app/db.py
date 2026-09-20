import sqlite3

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    duration_min INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS professionals (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

-- weekday: 0 = lunes ... 6 = domingo. Varias filas por dia permiten cortes (ej. siesta).
CREATE TABLE IF NOT EXISTS working_hours (
    professional_id INTEGER NOT NULL REFERENCES professionals(id),
    weekday INTEGER NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT
);

-- status: confirmed | cancelled
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    professional_id INTEGER NOT NULL REFERENCES professionals(id),
    service_id INTEGER NOT NULL REFERENCES services(id),
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmed'
);

CREATE TABLE IF NOT EXISTS waitlist (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    service_id INTEGER NOT NULL REFERENCES services(id),
    professional_id INTEGER REFERENCES professionals(id),
    day TEXT NOT NULL
);
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
