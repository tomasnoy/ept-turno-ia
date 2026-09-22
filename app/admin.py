"""Endpoints del panel del negocio. Todos requieren una sesion valida (login por email/clave)."""

import re
import sqlite3
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import scheduling, tenancy, waitlist
from app.auth import require_business
from app.deps import get_conn, get_now

UPCOMING_DAYS = 14
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

router = APIRouter(prefix="/api/admin")


@router.get("/check")
def check(business_id: int = Depends(require_business)) -> dict:
    """Sirve para validar la sesion al iniciar el panel."""
    return {"ok": True}


@router.get("/agenda")
def agenda(
    day: date | None = None,
    business_id: int = Depends(require_business),
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> dict:
    day = day or now.date()
    start = datetime(day.year, day.month, day.day)
    rows = conn.execute(
        """SELECT a.id, a.start, a.end, a.status, s.name AS service, s.id AS service_id,
                  p.name AS professional, p.id AS professional_id,
                  c.name AS customer, c.phone AS phone
           FROM appointments a
           JOIN services s ON s.id = a.service_id AND s.business_id = a.business_id
           JOIN professionals p ON p.id = a.professional_id AND p.business_id = a.business_id
           JOIN customers c ON c.id = a.customer_id AND c.business_id = a.business_id
           WHERE a.business_id = ? AND a.start >= ? AND a.start < ?
           ORDER BY a.start, p.name""",
        (business_id, start.isoformat(), (start + timedelta(days=1)).isoformat()),
    ).fetchall()

    today = datetime(now.year, now.month, now.day)
    counts = conn.execute(
        """SELECT substr(start, 1, 10) AS day, COUNT(*) AS n FROM appointments
           WHERE business_id = ? AND status IN ('confirmed', 'pending') AND start >= ? AND start < ?
           GROUP BY day""",
        (business_id, today.isoformat(), (today + timedelta(days=UPCOMING_DAYS)).isoformat()),
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


def _owned_appointment(conn: sqlite3.Connection, business_id: int, appointment_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT status, start FROM appointments WHERE id = ? AND business_id = ?", (appointment_id, business_id)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "El turno no existe.")
    return row


@router.post("/appointments/{appointment_id}/confirm")
def confirm(
    appointment_id: int, business_id: int = Depends(require_business), conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    if not scheduling.confirm(conn, business_id, appointment_id):
        _owned_appointment(conn, business_id, appointment_id)
        raise HTTPException(409, "Ese turno no está pendiente de confirmación.")
    return {"appointment_id": appointment_id, "status": "confirmed"}


@router.post("/appointments/{appointment_id}/cancel")
def cancel(
    appointment_id: int,
    business_id: int = Depends(require_business),
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> dict:
    freed_start = scheduling.cancel(conn, business_id, appointment_id)
    if freed_start is None:
        _owned_appointment(conn, business_id, appointment_id)
        raise HTTPException(409, "Ese turno ya estaba cancelado.")
    # Reacomodo: a quien esta esperando se le puede ofrecer el lugar que se acaba de liberar.
    freed_day = datetime.fromisoformat(freed_start).date()
    matches = waitlist.matches_for_day(conn, business_id, freed_day, now)
    return {
        "appointment_id": appointment_id,
        "status": "cancelled",
        "waitlist_matches": [{"id": m["id"], "customer": m["customer"]} for m in matches],
    }


class GiveSlotIn(BaseModel):
    professional_id: int
    start: datetime


@router.get("/waitlist")
def waiting(
    business_id: int = Depends(require_business),
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> dict:
    return {"entries": waitlist.waiting_list(conn, business_id, now)}


@router.post("/waitlist/{entry_id}/book")
def give_slot(
    entry_id: int,
    body: GiveSlotIn,
    business_id: int = Depends(require_business),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """Le da el turno a quien esperaba: crea la reserva y lo saca de la lista."""
    try:
        appointment_id = waitlist.fulfill(conn, business_id, entry_id, body.professional_id, body.start)
    except waitlist.EntryNotFound:
        raise HTTPException(404, "Esa persona ya no está en la lista.")
    except waitlist.EntryNotWaiting:
        raise HTTPException(409, "Esa persona ya fue atendida o quitada de la lista.")
    except scheduling.SlotUnavailable:
        raise HTTPException(409, "Ese horario ya no está disponible para esa persona. Actualizá la lista.")
    return {"appointment_id": appointment_id}


@router.post("/waitlist/{entry_id}/remove")
def remove_from_waitlist(
    entry_id: int, business_id: int = Depends(require_business), conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    try:
        waitlist.remove(conn, business_id, entry_id)
    except waitlist.EntryNotFound:
        raise HTTPException(404, "Esa persona ya no está en la lista.")
    except waitlist.EntryNotWaiting:
        raise HTTPException(409, "Esa persona ya fue atendida o quitada de la lista.")
    return {"entry_id": entry_id, "status": "removed"}


# --- Configuracion: marca, plan, servicios, profesionales, horarios ----------------------------


class BrandingIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    welcome_message: str | None = Field(default=None, min_length=1, max_length=300)
    logo_url: str | None = Field(default=None, max_length=500)
    color_primary: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("logo_url")
    @classmethod
    def _safe_logo_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("El logo debe ser una URL HTTPS válida y sin credenciales.")
        return value


@router.get("/business")
def get_business(business_id: int = Depends(require_business), conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    row = tenancy.get_by_id(conn, business_id)
    return tenancy.to_public(row)


@router.put("/business")
def put_business(
    body: BrandingIn, business_id: int = Depends(require_business), conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    tenancy.update_branding(conn, business_id, body.name, body.welcome_message, body.logo_url, body.color_primary)
    return tenancy.to_public(tenancy.get_by_id(conn, business_id))


class PlanIn(BaseModel):
    plan: str

    @field_validator("plan")
    @classmethod
    def _valid_plan(cls, value: str) -> str:
        if value not in tenancy.PLANS:
            raise ValueError(f"Plan invalido: {value}")
        return value


@router.put("/plan")
def put_plan(
    body: PlanIn, business_id: int = Depends(require_business), conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    """Cambia de plan. No procesa ningun cobro real: es una simulacion para la demo."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = tenancy.professional_count(conn, business_id)
        limit = tenancy.PLAN_PROFESSIONAL_LIMITS[body.plan]
        if limit is not None and current > limit:
            raise HTTPException(
                409,
                f"Tenés {current} profesionales cargados y el plan {tenancy.PLAN_LABELS[body.plan]} "
                f"permite hasta {limit}. Reducí la cantidad antes de bajar de plan.",
            )
        conn.execute("UPDATE businesses SET plan = ? WHERE id = ?", (body.plan, business_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return tenancy.to_public(tenancy.get_by_id(conn, business_id))


class ServiceIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    duration_min: int = Field(ge=5, le=480)
    active: bool = True


def _service_row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "name": r["name"], "duration_min": r["duration_min"], "active": bool(r["active"])}


@router.get("/services")
def list_services(
    business_id: int = Depends(require_business), conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    rows = conn.execute(
        "SELECT id, name, duration_min, active FROM services WHERE business_id = ? ORDER BY name", (business_id,)
    ).fetchall()
    return {"services": [_service_row(r) for r in rows]}


@router.post("/services")
def create_service(
    body: ServiceIn, business_id: int = Depends(require_business), conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    cur = conn.execute(
        "INSERT INTO services (business_id, name, duration_min, active) VALUES (?, ?, ?, ?)",
        (business_id, body.name, body.duration_min, int(body.active)),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, name, duration_min, active FROM services WHERE id = ? AND business_id = ?",
        (cur.lastrowid, business_id),
    ).fetchone()
    return _service_row(row)


@router.put("/services/{service_id}")
def update_service(
    service_id: int,
    body: ServiceIn,
    business_id: int = Depends(require_business),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    if conn.execute(
        "SELECT 1 FROM services WHERE id = ? AND business_id = ?", (service_id, business_id)
    ).fetchone() is None:
        raise HTTPException(404, "El servicio no existe.")
    conn.execute(
        "UPDATE services SET name = ?, duration_min = ?, active = ? WHERE id = ? AND business_id = ?",
        (body.name, body.duration_min, int(body.active), service_id, business_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, name, duration_min, active FROM services WHERE id = ? AND business_id = ?",
        (service_id, business_id),
    ).fetchone()
    return _service_row(row)


class ProfessionalIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    active: bool = True


def _professional_row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "name": r["name"], "active": bool(r["active"])}


@router.get("/professionals")
def list_professionals(
    business_id: int = Depends(require_business), conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    rows = conn.execute(
        "SELECT id, name, active FROM professionals WHERE business_id = ? ORDER BY name", (business_id,)
    ).fetchall()
    return {"professionals": [_professional_row(r) for r in rows]}


@router.post("/professionals")
def create_professional(
    body: ProfessionalIn,
    business_id: int = Depends(require_business),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    conn.execute("BEGIN IMMEDIATE")
    try:
        business = tenancy.get_by_id(conn, business_id)
        limit = tenancy.PLAN_PROFESSIONAL_LIMITS[business["plan"]]
        current = tenancy.professional_count(conn, business_id)
        if limit is not None and current >= limit:
            raise HTTPException(
                409,
                f"Tu plan {tenancy.PLAN_LABELS[business['plan']]} permite hasta {limit} "
                f"{'profesional' if limit == 1 else 'profesionales'}. Mejorá tu plan para agregar más.",
            )
        cur = conn.execute(
            "INSERT INTO professionals (business_id, name, active) VALUES (?, ?, ?)",
            (business_id, body.name, int(body.active)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    row = conn.execute(
        "SELECT id, name, active FROM professionals WHERE id = ? AND business_id = ?",
        (cur.lastrowid, business_id),
    ).fetchone()
    return _professional_row(row)


@router.put("/professionals/{professional_id}")
def update_professional(
    professional_id: int,
    body: ProfessionalIn,
    business_id: int = Depends(require_business),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    if conn.execute(
        "SELECT 1 FROM professionals WHERE id = ? AND business_id = ?", (professional_id, business_id)
    ).fetchone() is None:
        raise HTTPException(404, "El profesional no existe.")
    conn.execute(
        "UPDATE professionals SET name = ?, active = ? WHERE id = ? AND business_id = ?",
        (body.name, int(body.active), professional_id, business_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, name, active FROM professionals WHERE id = ? AND business_id = ?",
        (professional_id, business_id),
    ).fetchone()
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
def get_working_hours(
    business_id: int = Depends(require_business), conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    professionals = conn.execute(
        "SELECT id, name, active FROM professionals WHERE business_id = ? ORDER BY name", (business_id,)
    ).fetchall()
    hours = conn.execute(
        """SELECT professional_id, weekday, start, end FROM working_hours
           WHERE business_id = ? ORDER BY professional_id, weekday, start""",
        (business_id,),
    ).fetchall()
    return {
        "professionals": [_professional_row(r) for r in professionals],
        "hours": [dict(r) for r in hours],
    }


@router.put("/working-hours")
def set_working_hours(
    body: WorkingHoursIn, business_id: int = Depends(require_business), conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    if conn.execute(
        "SELECT 1 FROM professionals WHERE id = ? AND business_id = ?", (body.professional_id, business_id)
    ).fetchone() is None:
        raise HTTPException(404, "El profesional no existe.")
    conn.execute(
        "DELETE FROM working_hours WHERE business_id = ? AND professional_id = ? AND weekday = ?",
        (business_id, body.professional_id, body.weekday),
    )
    conn.executemany(
        "INSERT INTO working_hours (business_id, professional_id, weekday, start, end) VALUES (?, ?, ?, ?, ?)",
        [(business_id, body.professional_id, body.weekday, r.start, r.end) for r in body.ranges],
    )
    conn.commit()
    return {"professional_id": body.professional_id, "weekday": body.weekday, "ranges": [r.model_dump() for r in body.ranges]}
