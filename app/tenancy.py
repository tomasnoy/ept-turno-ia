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


class EmailTaken(Exception):
    pass


def _slugify(name: str) -> str:
    stripped = unicodedata.normalize("NFD", name)
    ascii_only = "".join(c for c in stripped if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
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
    return {
        "id": row["id"],
        "slug": row["slug"],
        "name": row["name"],
        "plan": row["plan"],
        "welcome_message": row["welcome_message"] or f"¡Hola! Soy el asistente de {row['name']}. Contame qué servicio querés y para cuándo.",
        "logo_url": row["logo_url"],
        "color_primary": row["color_primary"] or "#7a3e65",
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
) -> None:
    conn.execute(
        "UPDATE businesses SET name = ?, welcome_message = ?, logo_url = ?, color_primary = ? WHERE id = ?",
        (name, welcome_message, logo_url, color_primary, business_id),
    )
    conn.commit()


def update_plan(conn: sqlite3.Connection, business_id: int, plan: str) -> None:
    conn.execute("UPDATE businesses SET plan = ? WHERE id = ?", (plan, business_id))
    conn.commit()


def professional_count(conn: sqlite3.Connection, business_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM professionals WHERE business_id = ?", (business_id,)).fetchone()[0]
