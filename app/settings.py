"""Configuracion del negocio editable desde el panel (nombre, mensaje de bienvenida).

Se guarda en la tabla settings como pares clave/valor. Si una clave no esta seteada, se usa un
valor por defecto (la variable de entorno para el nombre, un texto generico para el resto).
"""

import sqlite3

from app import config

DEFAULT_WELCOME = "¡Hola! Soy el asistente de {name}. Contame qué servicio querés y para cuándo."


def get_all(conn: sqlite3.Connection) -> dict:
    rows = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    name = rows.get("business_name") or config.BUSINESS_NAME
    welcome = rows.get("welcome_message") or DEFAULT_WELCOME.format(name=name)
    return {"business_name": name, "welcome_message": welcome}


def update(conn: sqlite3.Connection, business_name: str | None, welcome_message: str | None) -> None:
    for key, value in (("business_name", business_name), ("welcome_message", welcome_message)):
        if not value:
            continue
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    conn.commit()
