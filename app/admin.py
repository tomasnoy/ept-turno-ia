"""Endpoints del panel del negocio. Todos requieren la clave de administrador."""

import sqlite3
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import scheduling, waitlist
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
def cancel(
    appointment_id: int, conn: sqlite3.Connection = Depends(get_conn), now: datetime = Depends(get_now)
) -> dict:
    row = conn.execute("SELECT status, start FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "El turno no existe.")
    if row["status"] == "cancelled":
        raise HTTPException(409, "Ese turno ya estaba cancelado.")
    scheduling.cancel(conn, appointment_id)
    # Reacomodo: a quien esta esperando se le puede ofrecer el lugar que se acaba de liberar.
    freed_day = datetime.fromisoformat(row["start"]).date()
    matches = waitlist.matches_for_day(conn, freed_day, now)
    return {
        "appointment_id": appointment_id,
        "status": "cancelled",
        "waitlist_matches": [{"id": m["id"], "customer": m["customer"]} for m in matches],
    }


class GiveSlotIn(BaseModel):
    professional_id: int
    start: datetime


@router.get("/waitlist")
def waiting(conn: sqlite3.Connection = Depends(get_conn), now: datetime = Depends(get_now)) -> dict:
    return {"entries": waitlist.waiting_list(conn, now)}


@router.post("/waitlist/{entry_id}/book")
def give_slot(entry_id: int, body: GiveSlotIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """Le da el turno a quien esperaba: crea la reserva y lo saca de la lista."""
    try:
        appointment_id = waitlist.fulfill(conn, entry_id, body.professional_id, body.start)
    except waitlist.EntryNotFound:
        raise HTTPException(404, "Esa persona ya no está en la lista.")
    except waitlist.EntryNotWaiting:
        raise HTTPException(409, "Esa persona ya fue atendida o quitada de la lista.")
    except scheduling.SlotUnavailable:
        raise HTTPException(409, "Ese horario ya no está disponible para esa persona. Actualizá la lista.")
    return {"appointment_id": appointment_id}


@router.post("/waitlist/{entry_id}/remove")
def remove_from_waitlist(entry_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        waitlist.remove(conn, entry_id)
    except waitlist.EntryNotFound:
        raise HTTPException(404, "Esa persona ya no está en la lista.")
    except waitlist.EntryNotWaiting:
        raise HTTPException(409, "Esa persona ya fue atendida o quitada de la lista.")
    return {"entry_id": entry_id, "status": "removed"}
