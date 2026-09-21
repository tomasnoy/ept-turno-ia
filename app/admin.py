"""Endpoints del panel del negocio. Todos requieren la clave de administrador."""

import sqlite3
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from app import scheduling
from app.auth import require_admin
from app.deps import get_conn, get_now

UPCOMING_DAYS = 14

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


@router.get("/check")
def check() -> dict:
    """Sirve para validar la clave al iniciar sesion."""
    return {"ok": True}


@router.get("/agenda")
def agenda(day: date | None = None, conn: sqlite3.Connection = Depends(get_conn), now: datetime = Depends(get_now)) -> dict:
    day = day or now.date()
    start = datetime(day.year, day.month, day.day)
    rows = conn.execute(
        """SELECT a.id, a.start, a.end, a.status, s.name AS service, s.id AS service_id,
                  p.name AS professional, p.id AS professional_id,
                  c.name AS customer, c.phone AS phone
           FROM appointments a
           JOIN services s ON s.id = a.service_id
           JOIN professionals p ON p.id = a.professional_id
           JOIN customers c ON c.id = a.customer_id
           WHERE a.start >= ? AND a.start < ?
           ORDER BY a.start, p.name""",
        (start.isoformat(), (start + timedelta(days=1)).isoformat()),
    ).fetchall()

    today = datetime(now.year, now.month, now.day)
    counts = conn.execute(
        """SELECT substr(start, 1, 10) AS day, COUNT(*) AS n FROM appointments
           WHERE status = 'confirmed' AND start >= ? AND start < ?
           GROUP BY day""",
        (today.isoformat(), (today + timedelta(days=UPCOMING_DAYS)).isoformat()),
    ).fetchall()
    by_day = {r["day"]: r["n"] for r in counts}
    upcoming = [
        {"day": (d := (today + timedelta(days=i)).date()).isoformat(), "count": by_day.get(d.isoformat(), 0)}
        for i in range(UPCOMING_DAYS)
    ]
    return {
        "day": day.isoformat(),
        "appointments": [dict(r) for r in rows],
        "upcoming": upcoming,
    }


@router.post("/appointments/{appointment_id}/cancel")
def cancel(appointment_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    row = conn.execute("SELECT status FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "El turno no existe.")
    if row["status"] == "cancelled":
        raise HTTPException(409, "Ese turno ya estaba cancelado.")
    scheduling.cancel(conn, appointment_id)
    return {"appointment_id": appointment_id, "status": "cancelled"}
