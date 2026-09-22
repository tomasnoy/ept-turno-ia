import sqlite3


def find_by_phone(conn: sqlite3.Connection, business_id: int, phone: str | None) -> int | None:
    """El telefono identifica al cliente dentro de un negocio: asi se lo reconoce cuando vuelve."""
    if not phone:
        return None
    row = conn.execute(
        "SELECT id FROM customers WHERE business_id = ? AND phone = ?", (business_id, phone)
    ).fetchone()
    return row["id"] if row else None


def create(conn: sqlite3.Connection, business_id: int, name: str, phone: str | None) -> int:
    return conn.execute(
        "INSERT INTO customers (business_id, name, phone) VALUES (?, ?, ?)", (business_id, name, phone)
    ).lastrowid
