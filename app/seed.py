"""Datos de ejemplo: una peluqueria. Solo cambia la configuracion para servir a otro rubro."""

import sqlite3


def seed_demo(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM services").fetchone()[0]:
        return
    conn.executemany(
        "INSERT INTO services (id, name, duration_min) VALUES (?, ?, ?)",
        [(1, "Corte de pelo", 45), (2, "Tintura", 90), (3, "Peinado", 30)],
    )
    conn.executemany(
        "INSERT INTO professionals (id, name) VALUES (?, ?)",
        [(1, "Laura"), (2, "Martina")],
    )
    hours = []
    for professional_id in (1, 2):
        for weekday in range(0, 5):  # lunes a viernes
            hours += [(professional_id, weekday, "09:00", "13:00"), (professional_id, weekday, "15:00", "19:00")]
        hours.append((professional_id, 5, "09:00", "14:00"))  # sabado
    conn.executemany("INSERT INTO working_hours VALUES (?, ?, ?, ?)", hours)
    conn.commit()
