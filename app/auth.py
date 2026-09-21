"""Acceso al panel del negocio con una clave compartida (ADMIN_TOKEN).

Si la clave no esta configurada el panel queda deshabilitado: nunca abierto por omision.
"""

import hmac
import time
from collections import defaultdict

from fastapi import Header, HTTPException, Request

from app import config

MAX_FAILURES = 10
WINDOW_SECONDS = 300

_failures: dict[str, list[float]] = defaultdict(list)


def reset_failures() -> None:
    _failures.clear()


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    if not config.ADMIN_TOKEN:
        raise HTTPException(503, "El panel no está habilitado: falta configurar ADMIN_TOKEN en el servidor.")
    ip = request.client.host if request.client else "desconocido"
    now = time.monotonic()
    recent = [t for t in _failures[ip] if now - t < WINDOW_SECONDS]
    _failures[ip] = recent
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(429, "Demasiados intentos fallidos. Esperá unos minutos y probá de nuevo.")
    supplied = (x_admin_token or "").encode()
    if not hmac.compare_digest(supplied, config.ADMIN_TOKEN.encode()):
        _failures[ip].append(now)
        raise HTTPException(401, "Clave incorrecta.")
