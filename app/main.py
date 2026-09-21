import re
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app import admin, config, db, flow, scheduling, seed
from app.deps import get_conn, get_llm, get_now
from app.llm.base import LLMError, LLMProvider

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect()
    db.init_db(conn)
    seed.seed_demo(conn)
    conn.close()
    yield


app = FastAPI(title="Gestor de turnos con IA", lifespan=lifespan)
app.include_router(admin.router)


class ContextIn(BaseModel):
    service_id: int | None = None
    professional_id: int | None = None
    day: date | None = None


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    context: ContextIn = ContextIn()


class BookIn(BaseModel):
    customer_name: str = Field(min_length=2, max_length=80)
    phone: str | None = Field(default=None, max_length=20)
    professional_id: int
    service_id: int
    start: datetime

    @field_validator("customer_name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("El nombre es demasiado corto")
        return value

    @field_validator("phone")
    @classmethod
    def _clean_phone(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not re.fullmatch(r"[0-9+\-() ]{6,20}", value):
            raise ValueError("El teléfono solo puede tener números, espacios, + - ( )")
        return value


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_provider": config.LLM_PROVIDER}


@app.get("/api/business")
def business(conn=Depends(get_conn)) -> dict:
    catalog = flow.load_catalog(conn)
    return {
        "name": config.BUSINESS_NAME,
        "services": [{"id": i, "name": n} for i, n in catalog.services],
        "professionals": [{"id": i, "name": n} for i, n in catalog.professionals],
    }


@app.post("/api/chat")
def chat(
    body: ChatIn,
    conn=Depends(get_conn),
    provider: LLMProvider = Depends(get_llm),
    now: datetime = Depends(get_now),
) -> dict:
    ctx = flow.Context(body.context.service_id, body.context.professional_id, body.context.day)
    try:
        result = flow.handle_message(conn, provider, body.message, ctx, now)
    except LLMError:
        raise HTTPException(503, "El asistente no está disponible en este momento. Probá de nuevo en unos segundos.")
    return {
        "reply": result.reply,
        "options": [
            {
                "professional_id": o.professional_id,
                "professional_name": o.professional_name,
                "start": o.start.isoformat(),
                "label": o.label,
            }
            for o in result.options
        ],
        "context": {
            "service_id": result.context.service_id,
            "professional_id": result.context.professional_id,
            "day": result.context.day.isoformat() if result.context.day else None,
        },
    }


@app.post("/api/book")
def book(body: BookIn, conn=Depends(get_conn)) -> dict:
    catalog = flow.load_catalog(conn)
    services = dict(catalog.services)
    professionals = dict(catalog.professionals)
    if body.service_id not in services or body.professional_id not in professionals:
        raise HTTPException(400, "Servicio o profesional inexistente")

    customer_id = None
    if body.phone:
        row = conn.execute("SELECT id FROM customers WHERE phone = ?", (body.phone,)).fetchone()
        customer_id = row["id"] if row else None
    try:
        # El turno se valida antes de crear al cliente, asi un horario ocupado no deja registros sueltos.
        if body.start not in scheduling.free_slots(conn, body.professional_id, body.service_id, body.start.date()):
            raise scheduling.SlotUnavailable(body.start.isoformat())
        if customer_id is None:
            customer_id = conn.execute(
                "INSERT INTO customers (name, phone) VALUES (?, ?)", (body.customer_name, body.phone)
            ).lastrowid
        appointment_id = scheduling.book(
            conn, customer_id, body.professional_id, body.service_id, body.start
        )
    except scheduling.SlotUnavailable:
        raise HTTPException(409, "Ese horario ya no está disponible. Elegí otro, por favor.")
    return {
        "appointment_id": appointment_id,
        "summary": (
            f"Turno confirmado: {services[body.service_id]} con {professionals[body.professional_id]}, "
            f"{flow.day_label(body.start.date())} a las {body.start:%H:%M}."
        ),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
def admin_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
