"""Alta de negocios y login del panel (email + clave, con sesion propia por negocio)."""

import re
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app import auth, tenancy
from app.deps import get_conn, get_now

router = APIRouter(prefix="/api")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=100)
    plan: str = "basico"

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        if not EMAIL_RE.fullmatch(value):
            raise ValueError("Ese email no parece válido.")
        return value.lower()

    @field_validator("plan")
    @classmethod
    def _valid_plan(cls, value: str) -> str:
        if value not in tenancy.PLANS:
            raise ValueError(f"Plan inválido: {value}")
        return value


@router.post("/signup")
def signup(
    body: SignupIn,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    now: datetime = Depends(get_now),
) -> dict:
    ip = request.client.host if request.client else "desconocido"
    auth.check_request_limit(f"signup:{ip}", limit=5, window_seconds=3600)
    try:
        business = tenancy.create(conn, body.business_name, body.email, body.password, body.plan, now)
    except tenancy.EmailTaken:
        raise HTTPException(409, "Ya hay una cuenta registrada con ese email.")
    token = auth.create_session(conn, business["id"], now)
    return {"session_token": token, "business": tenancy.to_public(business)}


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(
    body: LoginIn, request: Request, conn: sqlite3.Connection = Depends(get_conn), now: datetime = Depends(get_now)
) -> dict:
    ip = request.client.host if request.client else "desconocido"
    reservation = auth.begin_login(conn, ip, body.email)
    business = tenancy.authenticate(conn, body.email, body.password)
    if business is None:
        raise HTTPException(401, "Email o clave incorrectos.")
    auth.login_succeeded(conn, reservation)
    token = auth.create_session(conn, business["id"], now)
    return {"session_token": token, "business": tenancy.to_public(business)}


@router.post("/logout")
def logout(
    x_session_token: str | None = Header(default=None), conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    if x_session_token:
        auth.destroy_session(conn, x_session_token)
    return {"ok": True}
