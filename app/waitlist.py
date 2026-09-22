"""Lista de espera y reacomodo.

Quien no encuentra lugar se anota. Cuando el negocio libera un horario, este modulo decide a quien
ofrecerselo (por orden de llegada) y con que horarios. Todo es logica determinista: ningun dato
de clientes pasa por el modelo de IA.
"""

import sqlite3
from datetime import date, datetime

from app import scheduling
from app.flow import Catalog, load_catalog, options_for_day

MAX_WAITING_PER_CUSTOMER = 3
MAX_OFFERS = 3


class WaitlistFull(Exception):
    pass


class EntryNotFound(Exception):
    pass


class EntryNotWaiting(Exception):
    pass


def add_entry(
    conn: sqlite3.Connection,
    customer_id: int,
    service_id: int,
    professional_id: int | None,
    day: date,
    part_of_day: str,
    now: datetime,
) -> tuple[int, bool]:
    """Devuelve (id, creada). Si ya estaba anotado para lo mismo, no duplica."""
    existing = conn.execute(
        """SELECT id FROM waitlist WHERE status = 'waiting' AND customer_id = ? AND service_id = ?
           AND day = ? AND part_of_day = ? AND professional_id IS ?""",
        (customer_id, service_id, day.isoformat(), part_of_day, professional_id),
    ).fetchone()
    if existing:
        return existing["id"], False
    waiting = conn.execute(
        "SELECT COUNT(*) FROM waitlist WHERE status = 'waiting' AND customer_id = ?", (customer_id,)
    ).fetchone()[0]
    if waiting >= MAX_WAITING_PER_CUSTOMER:
        raise WaitlistFull()
    cur = conn.execute(
        """INSERT INTO waitlist (customer_id, service_id, professional_id, day, part_of_day, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (customer_id, service_id, professional_id, day.isoformat(), part_of_day, now.isoformat()),
    )
    conn.commit()
    return cur.lastrowid, True


def _rows(conn: sqlite3.Connection, where: str, params: tuple) -> list[sqlite3.Row]:
    return conn.execute(
        f"""SELECT w.id, w.customer_id, w.service_id, w.professional_id, w.day, w.part_of_day,
                   w.created_at, c.name AS customer, c.phone AS phone, s.name AS service,
                   p.name AS professional
            FROM waitlist w
            JOIN customers c ON c.id = w.customer_id
            JOIN services s ON s.id = w.service_id
            LEFT JOIN professionals p ON p.id = w.professional_id
            WHERE w.status = 'waiting' AND {where}
            ORDER BY w.created_at, w.id""",
        params,
    ).fetchall()


def offers_for(conn: sqlite3.Connection, catalog: Catalog, entry: sqlite3.Row, now: datetime) -> list[dict]:
    """Horarios que hoy le sirven a esta persona: su dia, su franja y su profesional."""
    options = options_for_day(
        conn, catalog, entry["service_id"], entry["professional_id"],
        date.fromisoformat(entry["day"]), entry["part_of_day"], None, now,
    )
    return [
        {
            "professional_id": o.professional_id,
            "professional_name": o.professional_name,
            "start": o.start.isoformat(),
            "label": f"{o.start:%H:%M} con {o.professional_name}",
        }
        for o in options[:MAX_OFFERS]
    ]


def _describe(conn, catalog, row: sqlite3.Row, now: datetime) -> dict:
    return {
        "id": row["id"],
        "customer": row["customer"],
        "phone": row["phone"],
        "service": row["service"],
        "professional": row["professional"],
        "day": row["day"],
        "part_of_day": row["part_of_day"],
        "created_at": row["created_at"],
        "offers": offers_for(conn, catalog, row, now),
    }


def waiting_list(conn: sqlite3.Connection, now: datetime) -> list[dict]:
    """Quienes esperan de hoy en adelante, por orden de llegada, con los horarios que hoy les sirven."""
    catalog = load_catalog(conn)
    return [_describe(conn, catalog, r, now) for r in _rows(conn, "w.day >= ?", (now.date().isoformat(),))]


def matches_for_day(conn: sqlite3.Connection, day: date, now: datetime) -> list[dict]:
    """A quienes se les puede ofrecer un lugar de ese dia ahora mismo (tras una cancelacion)."""
    catalog = load_catalog(conn)
    described = [_describe(conn, catalog, r, now) for r in _rows(conn, "w.day = ?", (day.isoformat(),))]
    return [d for d in described if d["offers"]]


def _get_waiting(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM waitlist WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise EntryNotFound()
    if row["status"] != "waiting":
        raise EntryNotWaiting()
    return row


def fulfill(conn: sqlite3.Connection, entry_id: int, professional_id: int, start: datetime) -> int:
    """Le da el turno a quien esperaba. Levanta SlotUnavailable si el horario ya no esta libre."""
    entry = _get_waiting(conn, entry_id)
    if entry["professional_id"] not in (None, professional_id):
        raise scheduling.SlotUnavailable("El cliente pidio otro profesional")
    if start.date().isoformat() != entry["day"]:
        raise scheduling.SlotUnavailable("El cliente esta anotado para otro dia")
    appointment_id = scheduling.book(
        conn, entry["customer_id"], professional_id, entry["service_id"], start, status="confirmed"
    )
    conn.execute("UPDATE waitlist SET status = 'fulfilled' WHERE id = ?", (entry_id,))
    conn.commit()
    return appointment_id


def remove(conn: sqlite3.Connection, entry_id: int) -> None:
    _get_waiting(conn, entry_id)
    conn.execute("UPDATE waitlist SET status = 'removed' WHERE id = ?", (entry_id,))
    conn.commit()
