"""Autenticacion multi-tenant: cada negocio tiene su propio email/clave y sus propias sesiones.

Las contraseñas se guardan con PBKDF2 (nunca en texto plano). El login devuelve un token de
sesión opaco que el panel manda en el header X-Session-Token; de ahi se deriva el business_id
que filtra todas las consultas de ese negocio.
"""

import hashlib
import hmac
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import Depends, Header, HTTPException

from app.deps import get_conn, get_now

PBKDF2_ITERATIONS = 200_000
SESSION_TTL_DAYS = 7
MAX_FAILURES = 10
WINDOW_SECONDS = 300

_failures: dict[str, list[float]] = defaultdict(list)


def reset_failures() -> None:
    _failures.clear()


def check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    recent = [t for t in _failures[ip] if now - t < WINDOW_SECONDS]
    _failures[ip] = recent
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(429, "Demasiados intentos fallidos. Esperá unos minutos y probá de nuevo.")


def record_failure(ip: str) -> None:
    _failures[ip].append(time.monotonic())


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()
    return f"{PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    except ValueError:
        return False
    return hmac.compare_digest(candidate, digest)


def create_session(conn, business_id: int, now: datetime) -> str:
    token = secrets.token_urlsafe(32)
    expires = now + timedelta(days=SESSION_TTL_DAYS)
    conn.execute(
        "INSERT INTO sessions (token, business_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, business_id, now.isoformat(), expires.isoformat()),
    )
    conn.commit()
    return token


def destroy_session(conn, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


def require_business(
    x_session_token: str | None = Header(default=None),
    conn=Depends(get_conn),
    now: datetime = Depends(get_now),
) -> int:
    """Devuelve el business_id dueño del token de sesión, o rechaza la request."""
    if not x_session_token:
        raise HTTPException(401, "Iniciá sesión para acceder al panel.")
    row = conn.execute(
        "SELECT business_id, expires_at FROM sessions WHERE token = ?", (x_session_token,)
    ).fetchone()
    if row is None or datetime.fromisoformat(row["expires_at"]) < now:
        raise HTTPException(401, "La sesión venció o no es válida. Iniciá sesión de nuevo.")
    return row["business_id"]
