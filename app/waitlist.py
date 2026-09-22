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
    business_id: int,
    customer_id: int,
    service_id: int,
    professional_id: int | None,
    day: date,
    part_of_day: str,
    now: datetime,
) -> tuple[int, bool]:
    """Devuelve (id, creada). Si ya estaba anotado para lo mismo, no duplica."""
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute(
            """SELECT id FROM waitlist WHERE status = 'waiting' AND business_id = ? AND customer_id = ?
               AND service_id = ? AND day = ? AND part_of_day = ? AND professional_id IS ?""",
            (business_id, customer_id, service_id, day.isoformat(), part_of_day, professional_id),
        ).fetchone()
        if existing:
            if owns_transaction:
                conn.commit()
            return existing["id"], False
        waiting = conn.execute(
            """SELECT COUNT(*) FROM waitlist
               WHERE status = 'waiting' AND business_id = ? AND customer_id = ?""",
            (business_id, customer_id),
        ).fetchone()[0]
        if waiting >= MAX_WAITING_PER_CUSTOMER:
            raise WaitlistFull()
        cur = conn.execute(
            """INSERT INTO waitlist
               (business_id, customer_id, service_id, professional_id, day, part_of_day, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (business_id, customer_id, service_id, professional_id, day.isoformat(), part_of_day, now.isoformat()),
        )
        if owns_transaction:
            conn.commit()
        return cur.lastrowid, True
    except Exception:
        if owns_transaction:
            conn.rollback()
        raise


def _rows(conn: sqlite3.Connection, business_id: int, where: str, params: tuple) -> list[sqlite3.Row]:
    return conn.execute(
        f"""SELECT w.id, w.customer_id, w.service_id, w.professional_id, w.day, w.part_of_day,
                   w.created_at, c.name AS customer, c.phone AS phone, s.name AS service,
                   p.name AS professional
            FROM waitlist w
            JOIN customers c ON c.id = w.customer_id AND c.business_id = w.business_id
            JOIN services s ON s.id = w.service_id AND s.business_id = w.business_id
            LEFT JOIN professionals p ON p.id = w.professional_id AND p.business_id = w.business_id
            WHERE w.status = 'waiting' AND w.business_id = ? AND {where}
            ORDER BY w.created_at, w.id""",
        (business_id, *params),
    ).fetchall()


def offers_for(
    conn: sqlite3.Connection,
    catalog: Catalog,
    entry: sqlite3.Row,
    now: datetime,
    cache: dict[tuple, list[dict]] | None = None,
) -> list[dict]:
    """Horarios que hoy le sirven a esta persona: su dia, su franja y su profesional."""
    key = (entry["service_id"], entry["professional_id"], entry["day"], entry["part_of_day"])
    if cache is not None and key in cache:
        return cache[key]
    options = options_for_day(
        conn, catalog, entry["service_id"], entry["professional_id"],
        date.fromisoformat(entry["day"]), entry["part_of_day"], None, now,
    )
    result = [
        {
            "professional_id": o.professional_id,
            "professional_name": o.professional_name,
            "start": o.start.isoformat(),
            "label": f"{o.start:%H:%M} con {o.professional_name}",
        }
        for o in options[:MAX_OFFERS]
    ]
    if cache is not None:
        cache[key] = result
    return result


def _describe(conn, catalog, row: sqlite3.Row, now: datetime, cache: dict[tuple, list[dict]]) -> dict:
    return {
        "id": row["id"],
        "customer": row["customer"],
        "phone": row["phone"],
        "service": row["service"],
        "professional": row["professional"],
        "day": row["day"],
        "part_of_day": row["part_of_day"],
        "created_at": row["created_at"],
        "offers": offers_for(conn, catalog, row, now, cache),
    }


def waiting_list(conn: sqlite3.Connection, business_id: int, now: datetime) -> list[dict]:
    """Quienes esperan de hoy en adelante, por orden de llegada, con los horarios que hoy les sirven."""
    catalog = load_catalog(conn, business_id)
    rows = _rows(conn, business_id, "w.day >= ?", (now.date().isoformat(),))
    cache: dict[tuple, list[dict]] = {}
    return [_describe(conn, catalog, r, now, cache) for r in rows]


def matches_for_day(conn: sqlite3.Connection, business_id: int, day: date, now: datetime) -> list[dict]:
    """A quienes se les puede ofrecer un lugar de ese dia ahora mismo (tras una cancelacion)."""
    catalog = load_catalog(conn, business_id)
    rows = _rows(conn, business_id, "w.day = ?", (day.isoformat(),))
    cache: dict[tuple, list[dict]] = {}
    described = [_describe(conn, catalog, r, now, cache) for r in rows]
    return [d for d in described if d["offers"]]


def _get_waiting(conn: sqlite3.Connection, business_id: int, entry_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM waitlist WHERE id = ? AND business_id = ?", (entry_id, business_id)).fetchone()
    if row is None:
        raise EntryNotFound()
    if row["status"] != "waiting":
        raise EntryNotWaiting()
    return row


def fulfill(conn: sqlite3.Connection, business_id: int, entry_id: int, professional_id: int, start: datetime) -> int:
    """Le da el turno a quien esperaba. Levanta SlotUnavailable si el horario ya no esta libre."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        entry = _get_waiting(conn, business_id, entry_id)
        if entry["professional_id"] not in (None, professional_id):
            raise scheduling.SlotUnavailable("El cliente pidio otro profesional")
        if start.date().isoformat() != entry["day"]:
            raise scheduling.SlotUnavailable("El cliente esta anotado para otro dia")
        appointment_id = scheduling.book(
            conn, business_id, entry["customer_id"], professional_id, entry["service_id"], start,
            status="confirmed",
        )
        conn.execute(
            "UPDATE waitlist SET status = 'fulfilled' WHERE id = ? AND business_id = ?",
            (entry_id, business_id),
        )
        conn.commit()
        return appointment_id
    except Exception:
        conn.rollback()
        raise


def remove(conn: sqlite3.Connection, business_id: int, entry_id: int) -> None:
    _get_waiting(conn, business_id, entry_id)
    conn.execute(
        "UPDATE waitlist SET status = 'removed' WHERE id = ? AND business_id = ?", (entry_id, business_id)
    )
    conn.commit()
