"""Negocio de ejemplo (una peluqueria) para probar la app recien clonada o en los tests."""

import sqlite3
from datetime import datetime

from app import tenancy

DEMO_EMAIL = "demo@ejemplo.com"
DEMO_PASSWORD = "demo1234"


def seed_demo(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Crea un negocio demo con catalogo solo si la base esta completamente vacia de negocios."""
    if conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]:
        return None
    business = tenancy.create(conn, "Peluquería Demo", DEMO_EMAIL, DEMO_PASSWORD, "premium", datetime.now())
    business_id = business["id"]
    conn.executemany(
        "INSERT INTO services (business_id, name, duration_min) VALUES (?, ?, ?)",
        [(business_id, "Corte de pelo", 45), (business_id, "Tintura", 90), (business_id, "Peinado", 30)],
    )
    professional_ids = []
    for name in ("Laura", "Martina"):
        cur = conn.execute("INSERT INTO professionals (business_id, name) VALUES (?, ?)", (business_id, name))
        professional_ids.append(cur.lastrowid)
    hours = []
    for professional_id in professional_ids:
        for weekday in range(0, 5):  # lunes a viernes
            hours += [
                (business_id, professional_id, weekday, "09:00", "13:00"),
                (business_id, professional_id, weekday, "15:00", "19:00"),
            ]
        hours.append((business_id, professional_id, 5, "09:00", "14:00"))  # sabado
    conn.executemany(
        "INSERT INTO working_hours (business_id, professional_id, weekday, start, end) VALUES (?, ?, ?, ?, ?)",
        hours,
    )
    conn.commit()
    return tenancy.get_by_id(conn, business_id)
