import sqlite3


def find_by_phone(conn: sqlite3.Connection, phone: str | None) -> int | None:
    """El telefono identifica al cliente: asi se reconoce cuando vuelve."""
    if not phone:
        return None
    row = conn.execute("SELECT id FROM customers WHERE phone = ?", (phone,)).fetchone()
    return row["id"] if row else None


def create(conn: sqlite3.Connection, name: str, phone: str | None) -> int:
    return conn.execute("INSERT INTO customers (name, phone) VALUES (?, ?)", (name, phone)).lastrowid
