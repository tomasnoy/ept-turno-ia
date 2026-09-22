"""Motor de disponibilidad: logica tradicional, sin IA.

La IA propone y este modulo valida y guarda. Ningun turno se escribe sin pasar por book().
"""

import sqlite3
from datetime import date, datetime, timedelta

SLOT_STEP_MIN = 15


class SlotUnavailable(Exception):
    pass


def _parse_hm(day: date, hm: str) -> datetime:
    hour, minute = hm.split(":")
    return datetime(day.year, day.month, day.day, int(hour), int(minute))


def _service_duration(conn: sqlite3.Connection, business_id: int, service_id: int) -> int:
    row = conn.execute(
        "SELECT duration_min FROM services WHERE id = ? AND business_id = ?",
        (service_id, business_id),
    ).fetchone()
    if row is None:
        raise SlotUnavailable(f"Servicio inexistente para el negocio: {service_id}")
    return row["duration_min"]


def _busy_intervals(conn: sqlite3.Connection, business_id: int, professional_id: int, day: date):
    day_start = datetime(day.year, day.month, day.day)
    rows = conn.execute(
        """SELECT start, end FROM appointments
           WHERE business_id = ? AND professional_id = ?
             AND status IN ('confirmed', 'pending') AND start < ? AND end > ?""",
        (business_id, professional_id, (day_start + timedelta(days=1)).isoformat(), day_start.isoformat()),
    ).fetchall()
    return [(datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])) for r in rows]


def free_slots(
    conn: sqlite3.Connection,
    business_id: int,
    professional_id: int,
    service_id: int,
    day: date,
    now: datetime | None = None,
) -> list[datetime]:
    """Horarios de inicio disponibles para un servicio con un profesional en un dia."""
    if conn.execute(
        "SELECT 1 FROM professionals WHERE id = ? AND business_id = ?",
        (professional_id, business_id),
    ).fetchone() is None:
        return []
    duration = timedelta(minutes=_service_duration(conn, business_id, service_id))
    windows = conn.execute(
        """SELECT start, end FROM working_hours
           WHERE business_id = ? AND professional_id = ? AND weekday = ?""",
        (business_id, professional_id, day.weekday()),
    ).fetchall()
    busy = _busy_intervals(conn, business_id, professional_id, day)
    step = timedelta(minutes=SLOT_STEP_MIN)

    slots: list[datetime] = []
    for w in windows:
        cursor, window_end = _parse_hm(day, w["start"]), _parse_hm(day, w["end"])
        while cursor + duration <= window_end:
            overlaps = any(cursor < b_end and cursor + duration > b_start for b_start, b_end in busy)
            in_past = now is not None and cursor <= now
            if not overlaps and not in_past:
                slots.append(cursor)
            cursor += step
    return sorted(slots)


def book(
    conn: sqlite3.Connection,
    business_id: int,
    customer_id: int,
    professional_id: int,
    service_id: int,
    start: datetime,
    status: str = "pending",
) -> int:
    """Crea el turno si el horario esta libre. Devuelve el id del turno.

    Nace en estado `status` (pendiente por defecto): el negocio lo confirma o cancela desde el
    panel. Las asignaciones que hace el propio negocio (ej. lista de espera) pueden nacer
    confirmadas directamente pasando status="confirmed".
    """
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        customer = conn.execute(
            "SELECT 1 FROM customers WHERE id = ? AND business_id = ?", (customer_id, business_id)
        ).fetchone()
        if customer is None or start not in free_slots(
            conn, business_id, professional_id, service_id, start.date()
        ):
            raise SlotUnavailable(f"{start.isoformat()} no esta disponible")
        end = start + timedelta(minutes=_service_duration(conn, business_id, service_id))
        cur = conn.execute(
            """INSERT INTO appointments
               (business_id, customer_id, professional_id, service_id, start, end, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (business_id, customer_id, professional_id, service_id, start.isoformat(), end.isoformat(), status),
        )
        if owns_transaction:
            conn.commit()
        return cur.lastrowid
    except Exception:
        if owns_transaction:
            conn.rollback()
        raise


def confirm(conn: sqlite3.Connection, business_id: int, appointment_id: int) -> bool:
    cur = conn.execute(
        """UPDATE appointments SET status = 'confirmed'
           WHERE id = ? AND business_id = ? AND status = 'pending'""",
        (appointment_id, business_id),
    )
    conn.commit()
    return cur.rowcount == 1


def cancel(conn: sqlite3.Connection, business_id: int, appointment_id: int) -> str | None:
    row = conn.execute(
        """UPDATE appointments SET status = 'cancelled'
           WHERE id = ? AND business_id = ? AND status != 'cancelled'
           RETURNING start""",
        (appointment_id, business_id),
    ).fetchone()
    conn.commit()
    return row["start"] if row else None
