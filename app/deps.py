"""Dependencias compartidas de FastAPI (se sobreescriben en los tests)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app import config, db
from app.llm.base import LLMProvider
from app.llm.factory import get_provider


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def get_llm() -> LLMProvider:
    return get_provider()


def get_now() -> datetime:
    """Hora local del negocio (el servidor puede estar en otra zona horaria)."""
    return datetime.now(ZoneInfo(config.TIMEZONE)).replace(tzinfo=None)
