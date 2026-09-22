import sqlite3

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS professionals (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

-- configuracion editable del negocio (nombre, mensaje de bienvenida, etc.)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
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

-- status: pending | confirmed | cancelled. Los turnos nacen pendientes hasta que el negocio los confirma.
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    professional_id INTEGER NOT NULL REFERENCES professionals(id),
    service_id INTEGER NOT NULL REFERENCES services(id),
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
);

-- status: waiting | fulfilled | removed. part_of_day: any | morning | afternoon | evening
CREATE TABLE IF NOT EXISTS waitlist (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    service_id INTEGER NOT NULL REFERENCES services(id),
    professional_id INTEGER REFERENCES professionals(id),
    day TEXT NOT NULL,
    part_of_day TEXT NOT NULL DEFAULT 'any',
    status TEXT NOT NULL DEFAULT 'waiting',
    created_at TEXT NOT NULL DEFAULT ''
);
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columnas agregadas despues de la primera version del esquema, para bases ya creadas.
MIGRATIONS = {
    "waitlist": {
        "part_of_day": "TEXT NOT NULL DEFAULT 'any'",
        "status": "TEXT NOT NULL DEFAULT 'waiting'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
    },
    "services": {"active": "INTEGER NOT NULL DEFAULT 1"},
    "professionals": {"active": "INTEGER NOT NULL DEFAULT 1"},
}


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, columns in MIGRATIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    conn.commit()
