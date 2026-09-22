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

CREATE TABLE IF NOT EXISTS login_rate_limits (
    key TEXT PRIMARY KEY,
    failures INTEGER NOT NULL,
    window_started REAL NOT NULL,
    updated_at REAL NOT NULL
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

INDEXES_AND_TENANT_GUARDS = """
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_business_created ON sessions(business_id, created_at);
CREATE INDEX IF NOT EXISTS idx_login_rate_limits_window ON login_rate_limits(window_started);
CREATE INDEX IF NOT EXISTS idx_services_business_active ON services(business_id, active);
CREATE INDEX IF NOT EXISTS idx_professionals_business_active ON professionals(business_id, active);
CREATE INDEX IF NOT EXISTS idx_working_hours_lookup
    ON working_hours(business_id, professional_id, weekday, start);
CREATE INDEX IF NOT EXISTS idx_customers_business_phone ON customers(business_id, phone);
CREATE INDEX IF NOT EXISTS idx_appointments_business_start ON appointments(business_id, start);
CREATE INDEX IF NOT EXISTS idx_appointments_availability
    ON appointments(business_id, professional_id, status, start, end);
CREATE INDEX IF NOT EXISTS idx_waitlist_business_status_day
    ON waitlist(business_id, status, day, created_at);

CREATE TRIGGER IF NOT EXISTS guard_working_hours_tenant_insert
BEFORE INSERT ON working_hours
WHEN NOT EXISTS (
    SELECT 1 FROM professionals p
    WHERE p.id = NEW.professional_id AND p.business_id = NEW.business_id
)
BEGIN
    SELECT RAISE(ABORT, 'professional tenant mismatch');
END;

CREATE TRIGGER IF NOT EXISTS guard_working_hours_tenant_update
BEFORE UPDATE OF business_id, professional_id ON working_hours
WHEN NOT EXISTS (
    SELECT 1 FROM professionals p
    WHERE p.id = NEW.professional_id AND p.business_id = NEW.business_id
)
BEGIN
    SELECT RAISE(ABORT, 'professional tenant mismatch');
END;

CREATE TRIGGER IF NOT EXISTS guard_appointments_tenant_insert
BEFORE INSERT ON appointments
WHEN NOT EXISTS (SELECT 1 FROM customers c WHERE c.id = NEW.customer_id AND c.business_id = NEW.business_id)
  OR NOT EXISTS (SELECT 1 FROM professionals p WHERE p.id = NEW.professional_id AND p.business_id = NEW.business_id)
  OR NOT EXISTS (SELECT 1 FROM services s WHERE s.id = NEW.service_id AND s.business_id = NEW.business_id)
BEGIN
    SELECT RAISE(ABORT, 'appointment tenant mismatch');
END;

CREATE TRIGGER IF NOT EXISTS guard_appointments_tenant_update
BEFORE UPDATE OF business_id, customer_id, professional_id, service_id ON appointments
WHEN NOT EXISTS (SELECT 1 FROM customers c WHERE c.id = NEW.customer_id AND c.business_id = NEW.business_id)
  OR NOT EXISTS (SELECT 1 FROM professionals p WHERE p.id = NEW.professional_id AND p.business_id = NEW.business_id)
  OR NOT EXISTS (SELECT 1 FROM services s WHERE s.id = NEW.service_id AND s.business_id = NEW.business_id)
BEGIN
    SELECT RAISE(ABORT, 'appointment tenant mismatch');
END;

CREATE TRIGGER IF NOT EXISTS guard_waitlist_tenant_insert
BEFORE INSERT ON waitlist
WHEN NOT EXISTS (SELECT 1 FROM customers c WHERE c.id = NEW.customer_id AND c.business_id = NEW.business_id)
  OR NOT EXISTS (SELECT 1 FROM services s WHERE s.id = NEW.service_id AND s.business_id = NEW.business_id)
  OR (NEW.professional_id IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM professionals p WHERE p.id = NEW.professional_id AND p.business_id = NEW.business_id
  ))
BEGIN
    SELECT RAISE(ABORT, 'waitlist tenant mismatch');
END;

CREATE TRIGGER IF NOT EXISTS guard_waitlist_tenant_update
BEFORE UPDATE OF business_id, customer_id, professional_id, service_id ON waitlist
WHEN NOT EXISTS (SELECT 1 FROM customers c WHERE c.id = NEW.customer_id AND c.business_id = NEW.business_id)
  OR NOT EXISTS (SELECT 1 FROM services s WHERE s.id = NEW.service_id AND s.business_id = NEW.business_id)
  OR (NEW.professional_id IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM professionals p WHERE p.id = NEW.professional_id AND p.business_id = NEW.business_id
  ))
BEGIN
    SELECT RAISE(ABORT, 'waitlist tenant mismatch');
END;
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI puede resolver las dependencias sync de un mismo request
    # (por ejemplo auth.require_business y el conn del endpoint) en threads distintos del pool.
    conn = sqlite3.connect(path or config.DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
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
    # WAL permite lectores durante una escritura. En bases en memoria SQLite conserva "memory".
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    for table, columns in MIGRATIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    conn.commit()
    _bootstrap_legacy_business(conn)
    conn.executescript(INDEXES_AND_TENANT_GUARDS)
    conn.commit()
