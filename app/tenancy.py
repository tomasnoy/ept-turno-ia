"""Alta y datos de cada negocio (tenant) del SaaS.

Cada negocio tiene su propio login, su propio plan y su propia marca (nombre, mensaje de
bienvenida, logo, color). Todo lo demas (servicios, profesionales, turnos) se filtra siempre
por business_id: ningun negocio puede ver ni tocar datos de otro.
"""

import re
import sqlite3
import unicodedata
from datetime import datetime

from app import auth

PLANS = ("basico", "pro", "premium")
PLAN_LABELS = {"basico": "Básico", "pro": "Pro", "premium": "Premium"}
# Limite de profesionales por plan. None = sin limite.
PLAN_PROFESSIONAL_LIMITS: dict[str, int | None] = {"basico": 1, "pro": 5, "premium": None}
SLUG_MAX_LEN = 60
MAX_EXAMPLE_PROMPTS = 3
DEFAULT_EXAMPLE_PROMPTS = [
    "Quiero reservar un turno para mañana",
    "¿Qué turnos hay para el viernes?",
    "Necesito un turno para el sábado a la mañana",
]


class EmailTaken(Exception):
    pass


def _slugify(name: str) -> str:
    stripped = unicodedata.normalize("NFD", name)
    ascii_only = "".join(c for c in stripped if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    slug = slug[:SLUG_MAX_LEN].strip("-")
    return slug or "negocio"


def _unique_slug(conn: sqlite3.Connection, name: str) -> str:
    base = _slugify(name)
    slug = base
    i = 2
    while conn.execute("SELECT 1 FROM businesses WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{i}"
        i += 1
    return slug


def to_public(row: sqlite3.Row) -> dict:
    raw_prompts = row["example_prompts"] if "example_prompts" in row.keys() else None
    example_prompts = [p for p in raw_prompts.split("\n") if p] if raw_prompts else DEFAULT_EXAMPLE_PROMPTS
    return {
        "id": row["id"],
        "slug": row["slug"],
        "name": row["name"],
        "plan": row["plan"],
        "welcome_message": row["welcome_message"] or f"¡Hola! Soy el asistente de {row['name']}. Contame qué servicio querés y para cuándo.",
        "logo_url": row["logo_url"],
        "color_primary": row["color_primary"] or "#7a3e65",
        "example_prompts": example_prompts,
        "professional_limit": PLAN_PROFESSIONAL_LIMITS[row["plan"]],
    }


def get_by_id(conn: sqlite3.Connection, business_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()


def get_by_slug(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM businesses WHERE slug = ?", (slug,)).fetchone()


def get_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM businesses WHERE email = ?", (email.lower(),)).fetchone()


def create(conn: sqlite3.Connection, name: str, email: str, password: str, plan: str, now: datetime) -> sqlite3.Row:
    email = email.lower().strip()
    if get_by_email(conn, email):
        raise EmailTaken()
    slug = _unique_slug(conn, name)
    cur = conn.execute(
        """INSERT INTO businesses (slug, name, email, password_hash, plan, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (slug, name, email, auth.hash_password(password), plan, now.isoformat()),
    )
    conn.commit()
    return get_by_id(conn, cur.lastrowid)


def ensure_default_professional(conn: sqlite3.Connection, business_id: int, business_name: str) -> None:
    """Si el negocio no tiene ningun profesional, crea uno implicito para que pueda recibir turnos."""
    if professional_count(conn, business_id):
        return
    conn.execute(
        "INSERT INTO professionals (business_id, name, active) VALUES (?, ?, 1)",
        (business_id, business_name),
    )


DEFAULT_SERVICE_NAME = "Turno"
DEFAULT_SERVICE_DURATION_MIN = 30


def service_count(conn: sqlite3.Connection, business_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM services WHERE business_id = ?", (business_id,)).fetchone()[0]


def ensure_default_service(conn: sqlite3.Connection, business_id: int) -> None:
    """Si el negocio no tiene ningun servicio, crea uno generico para que pueda recibir turnos."""
    if service_count(conn, business_id):
        return
    conn.execute(
        "INSERT INTO services (business_id, name, duration_min, active) VALUES (?, ?, ?, 1)",
        (business_id, DEFAULT_SERVICE_NAME, DEFAULT_SERVICE_DURATION_MIN),
    )


def authenticate(conn: sqlite3.Connection, email: str, password: str) -> sqlite3.Row | None:
    row = get_by_email(conn, email)
    if row is None or not auth.verify_password(password, row["password_hash"]):
        return None
    return row


def update_branding(
    conn: sqlite3.Connection,
    business_id: int,
    name: str,
    welcome_message: str | None,
    logo_url: str | None,
    color_primary: str | None,
    example_prompts: list[str] | None = None,
) -> None:
    prompts_value = "\n".join(example_prompts) if example_prompts else None
    conn.execute(
        "UPDATE businesses SET name = ?, welcome_message = ?, logo_url = ?, color_primary = ?, example_prompts = ? "
        "WHERE id = ?",
        (name, welcome_message, logo_url, color_primary, prompts_value, business_id),
    )
    conn.commit()


def update_plan(conn: sqlite3.Connection, business_id: int, plan: str) -> None:
    conn.execute("UPDATE businesses SET plan = ? WHERE id = ?", (plan, business_id))
    conn.commit()


def professional_count(conn: sqlite3.Connection, business_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM professionals WHERE business_id = ?", (business_id,)).fetchone()[0]
