import sqlite3
from datetime import datetime, timezone

from app import config

# plan: basico | pro | premium. basico es gratis; los otros se "activan" sin cobro real (demo).
SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'basico',
    welcome_message TEXT,
    logo_url TEXT,
    color_primary TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    name TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS professionals (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

-- weekday: 0 = lunes ... 6 = domingo. Varias filas por dia permiten cortes (ej. siesta).
CREATE TABLE IF NOT EXISTS working_hours (
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    professional_id INTEGER NOT NULL REFERENCES professionals(id),
    weekday INTEGER NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    name TEXT NOT NULL,
    phone TEXT
);

-- status: pending | confirmed | cancelled. Los turnos nacen pendientes hasta que el negocio los confirma.
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
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
    business_id INTEGER NOT NULL REFERENCES businesses(id),
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
    # check_same_thread=False: FastAPI puede resolver las dependencias sync de un mismo request
    # (por ejemplo auth.require_business y el conn del endpoint) en threads distintos del pool.
    conn = sqlite3.connect(path or config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columnas agregadas despues de la primera version del esquema, para bases ya creadas.
MIGRATIONS = {
    "waitlist": {
        "part_of_day": "TEXT NOT NULL DEFAULT 'any'",
        "status": "TEXT NOT NULL DEFAULT 'waiting'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "business_id": "INTEGER NOT NULL DEFAULT 1",
    },
    "services": {"active": "INTEGER NOT NULL DEFAULT 1", "business_id": "INTEGER NOT NULL DEFAULT 1"},
    "professionals": {"active": "INTEGER NOT NULL DEFAULT 1", "business_id": "INTEGER NOT NULL DEFAULT 1"},
    "working_hours": {"business_id": "INTEGER NOT NULL DEFAULT 1"},
    "customers": {"business_id": "INTEGER NOT NULL DEFAULT 1"},
    "appointments": {"business_id": "INTEGER NOT NULL DEFAULT 1"},
}


def _bootstrap_legacy_business(conn: sqlite3.Connection) -> None:
    """Bases de antes del SaaS tenian un solo negocio sin tabla businesses.

    Si la migracion de arriba dejo filas con business_id = 1 pero no existe ese negocio,
    se crea a partir de la configuracion vieja (BUSINESS_NAME / ADMIN_TOKEN) para no perder datos.
    """
    if conn.execute("SELECT 1 FROM businesses WHERE id = 1").fetchone():
        return
    has_legacy_data = conn.execute("SELECT COUNT(*) FROM services").fetchone()[0]
    if not has_legacy_data:
        return
    from app import auth  # import tardio: evita ciclo de imports con config

    conn.execute(
        """INSERT INTO businesses (id, slug, name, email, password_hash, plan, created_at)
           VALUES (1, 'demo', ?, 'demo@local', ?, 'premium', ?)""",
        (
            config.BUSINESS_NAME,
            auth.hash_password(config.ADMIN_TOKEN or "cambiar1234"),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, columns in MIGRATIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    conn.commit()
    _bootstrap_legacy_business(conn)
