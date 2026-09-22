"""Autenticacion multi-tenant: cada negocio tiene su propio email/clave y sus propias sesiones.

Las contraseñas se guardan con PBKDF2 (nunca en texto plano). El login devuelve un token de
sesión opaco que el panel manda en el header X-Session-Token; de ahi se deriva el business_id
que filtra todas las consultas de ese negocio.
"""

import hashlib
import hmac
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta

from fastapi import Depends, Header, HTTPException

from app.deps import get_conn, get_now

PBKDF2_ITERATIONS = 200_000
SESSION_TTL_DAYS = 7
MAX_FAILURES = 10
WINDOW_SECONDS = 300
MAX_RATE_LIMIT_BUCKETS = 10_000
MAX_ACTIVE_SESSIONS = 5

_request_events: OrderedDict[str, list[float]] = OrderedDict()
_request_events_lock = threading.Lock()


def reset_failures() -> None:
    with _request_events_lock:
        _request_events.clear()


def begin_login(conn, ip: str, email: str) -> tuple[str, str]:
    """Reserva atomica y persistente de un intento por IP y cuenta."""
    keys = (f"ip:{ip}", f"account:{email.lower().strip()}")
    now = time.time()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM login_rate_limits WHERE window_started <= ?", (now - WINDOW_SECONDS,))
        counts = {
            key: (row["failures"] if (row := conn.execute(
                "SELECT failures FROM login_rate_limits WHERE key = ?", (key,)
            ).fetchone()) else 0)
            for key in keys
        }
        if any(count >= MAX_FAILURES for count in counts.values()):
            conn.commit()
            raise HTTPException(429, "Demasiados intentos fallidos. Esperá unos minutos y probá de nuevo.")
        new_keys = sum(1 for count in counts.values() if count == 0)
        total = conn.execute("SELECT COUNT(*) FROM login_rate_limits").fetchone()[0]
        if total + new_keys > MAX_RATE_LIMIT_BUCKETS:
            conn.commit()
            raise HTTPException(429, "El servicio de acceso está temporalmente saturado. Probá más tarde.")
        for key in keys:
            conn.execute(
                """INSERT INTO login_rate_limits (key, failures, window_started, updated_at)
                   VALUES (?, 1, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET failures = failures + 1, updated_at = excluded.updated_at""",
                (key, now, now),
            )
        conn.commit()
        return keys
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def login_succeeded(conn, keys: tuple[str, str]) -> None:
    """Un intento exitoso no consume el cupo; quita solo su reserva pendiente."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        for key in keys:
            conn.execute("UPDATE login_rate_limits SET failures = failures - 1 WHERE key = ?", (key,))
        conn.execute("DELETE FROM login_rate_limits WHERE failures <= 0")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def check_request_limit(key: str, limit: int, window_seconds: int) -> None:
    """Limite local acotado para endpoints publicos; el proxy debe aportar el limite distribuido."""
    now = time.monotonic()
    with _request_events_lock:
        recent = [t for t in _request_events.get(key, ()) if now - t < window_seconds]
        if len(recent) >= limit:
            raise HTTPException(429, "Demasiadas solicitudes. Esperá unos minutos y probá de nuevo.")
        recent.append(now)
        _request_events[key] = recent
        _request_events.move_to_end(key)
        while len(_request_events) > MAX_RATE_LIMIT_BUCKETS:
            _request_events.popitem(last=False)


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
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))
    conn.execute(
        "INSERT INTO sessions (token, business_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, business_id, now.isoformat(), expires.isoformat()),
    )
    conn.execute(
        """DELETE FROM sessions
           WHERE business_id = ? AND token NOT IN (
               SELECT token FROM sessions WHERE business_id = ?
               ORDER BY created_at DESC, rowid DESC LIMIT ?
           )""",
        (business_id, business_id, MAX_ACTIVE_SESSIONS),
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
    if row is None:
        raise HTTPException(401, "La sesión venció o no es válida. Iniciá sesión de nuevo.")
    if datetime.fromisoformat(row["expires_at"]) <= now:
        conn.execute("DELETE FROM sessions WHERE token = ?", (x_session_token,))
        conn.commit()
        raise HTTPException(401, "La sesión venció o no es válida. Iniciá sesión de nuevo.")
    return row["business_id"]
