"""Endpoints del panel del negocio. Todos requieren la clave de administrador."""

import re
import sqlite3
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import scheduling, settings as settings_module, waitlist
from app.auth import require_admin
from app.deps import get_conn, get_now

UPCOMING_DAYS = 14
WEEKDAYS_RANGE = range(0, 7)
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

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
           WHERE status IN ('confirmed', 'pending') AND start >= ? AND start < ?
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


@router.post("/appointments/{appointment_id}/confirm")
def confirm(appointment_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    row = conn.execute("SELECT status FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "El turno no existe.")
    if row["status"] != "pending":
        raise HTTPException(409, "Ese turno no está pendiente de confirmación.")
    scheduling.confirm(conn, appointment_id)
    return {"appointment_id": appointment_id, "status": "confirmed"}


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


# --- Configuracion: interfaz, servicios, profesionales, horarios ------------------------------


class SettingsIn(BaseModel):
    business_name: str | None = Field(default=None, min_length=1, max_length=80)
    welcome_message: str | None = Field(default=None, min_length=1, max_length=300)


@router.get("/settings")
def get_settings(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return settings_module.get_all(conn)


@router.put("/settings")
def put_settings(body: SettingsIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    settings_module.update(conn, body.business_name, body.welcome_message)
    return settings_module.get_all(conn)


class ServiceIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    duration_min: int = Field(ge=5, le=480)
    active: bool = True


def _service_row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "name": r["name"], "duration_min": r["duration_min"], "active": bool(r["active"])}


@router.get("/services")
def list_services(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    rows = conn.execute("SELECT id, name, duration_min, active FROM services ORDER BY name").fetchall()
    return {"services": [_service_row(r) for r in rows]}


@router.post("/services")
def create_service(body: ServiceIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    cur = conn.execute(
        "INSERT INTO services (name, duration_min, active) VALUES (?, ?, ?)",
        (body.name, body.duration_min, int(body.active)),
    )
    conn.commit()
    row = conn.execute("SELECT id, name, duration_min, active FROM services WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _service_row(row)


@router.put("/services/{service_id}")
def update_service(service_id: int, body: ServiceIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    if conn.execute("SELECT 1 FROM services WHERE id = ?", (service_id,)).fetchone() is None:
        raise HTTPException(404, "El servicio no existe.")
    conn.execute(
        "UPDATE services SET name = ?, duration_min = ?, active = ? WHERE id = ?",
        (body.name, body.duration_min, int(body.active), service_id),
    )
    conn.commit()
    row = conn.execute("SELECT id, name, duration_min, active FROM services WHERE id = ?", (service_id,)).fetchone()
    return _service_row(row)


class ProfessionalIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    active: bool = True


def _professional_row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "name": r["name"], "active": bool(r["active"])}


@router.get("/professionals")
def list_professionals(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    rows = conn.execute("SELECT id, name, active FROM professionals ORDER BY name").fetchall()
    return {"professionals": [_professional_row(r) for r in rows]}


@router.post("/professionals")
def create_professional(body: ProfessionalIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    cur = conn.execute(
        "INSERT INTO professionals (name, active) VALUES (?, ?)", (body.name, int(body.active))
    )
    conn.commit()
    row = conn.execute("SELECT id, name, active FROM professionals WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _professional_row(row)


@router.put("/professionals/{professional_id}")
def update_professional(
    professional_id: int, body: ProfessionalIn, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    if conn.execute("SELECT 1 FROM professionals WHERE id = ?", (professional_id,)).fetchone() is None:
        raise HTTPException(404, "El profesional no existe.")
    conn.execute(
        "UPDATE professionals SET name = ?, active = ? WHERE id = ?",
        (body.name, int(body.active), professional_id),
    )
    conn.commit()
    row = conn.execute("SELECT id, name, active FROM professionals WHERE id = ?", (professional_id,)).fetchone()
    return _professional_row(row)


class HourRange(BaseModel):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _valid_hhmm(cls, value: str) -> str:
        if not HHMM.fullmatch(value):
            raise ValueError("La hora debe tener formato HH:MM (24hs).")
        return value


class WorkingHoursIn(BaseModel):
    professional_id: int
    weekday: int = Field(ge=0, le=6)
    ranges: list[HourRange]

    @field_validator("ranges")
    @classmethod
    def _no_overlaps(cls, ranges: list[HourRange]) -> list[HourRange]:
        ordered = sorted(ranges, key=lambda r: r.start)
        for r in ordered:
            if r.start >= r.end:
                raise ValueError(f"El horario {r.start}-{r.end} no es valido: debe empezar antes de terminar.")
        for prev, nxt in zip(ordered, ordered[1:]):
            if prev.end > nxt.start:
                raise ValueError(f"Los horarios {prev.start}-{prev.end} y {nxt.start}-{nxt.end} se superponen.")
        return ordered


@router.get("/working-hours")
def get_working_hours(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    professionals = conn.execute("SELECT id, name, active FROM professionals ORDER BY name").fetchall()
    hours = conn.execute(
        "SELECT professional_id, weekday, start, end FROM working_hours ORDER BY professional_id, weekday, start"
    ).fetchall()
    return {
        "professionals": [_professional_row(r) for r in professionals],
        "hours": [dict(r) for r in hours],
    }


@router.put("/working-hours")
def set_working_hours(body: WorkingHoursIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    if conn.execute("SELECT 1 FROM professionals WHERE id = ?", (body.professional_id,)).fetchone() is None:
        raise HTTPException(404, "El profesional no existe.")
    conn.execute(
        "DELETE FROM working_hours WHERE professional_id = ? AND weekday = ?",
        (body.professional_id, body.weekday),
    )
    conn.executemany(
        "INSERT INTO working_hours (professional_id, weekday, start, end) VALUES (?, ?, ?, ?)",
        [(body.professional_id, body.weekday, r.start, r.end) for r in body.ranges],
    )
    conn.commit()
    return {"professional_id": body.professional_id, "weekday": body.weekday, "ranges": [r.model_dump() for r in body.ranges]}
