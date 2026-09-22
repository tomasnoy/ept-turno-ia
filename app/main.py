import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app import admin, config, customers, db, flow, scheduling, seed, waitlist
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


def _clean_name(value: str) -> str:
    value = value.strip()
    if len(value) < 2:
        raise ValueError("El nombre es demasiado corto")
    return value


def _clean_phone(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if not re.fullmatch(r"[0-9+\-() ]{6,20}", value):
        raise ValueError("El teléfono solo puede tener números, espacios, + - ( )")
    return value


class BookIn(BaseModel):
    customer_name: str = Field(min_length=2, max_length=80)
    phone: str | None = Field(default=None, max_length=20)
    professional_id: int
    service_id: int
    start: datetime

    _name = field_validator("customer_name")(_clean_name)
    _phone = field_validator("phone")(_clean_phone)


class WaitlistIn(BaseModel):
    customer_name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=6, max_length=20)  # obligatorio: el negocio tiene que poder avisar
    service_id: int
    professional_id: int | None = None
    day: date
    part_of_day: str = "any"

    _name = field_validator("customer_name")(_clean_name)
    _phone = field_validator("phone")(_clean_phone)

    @field_validator("part_of_day")
    @classmethod
    def _valid_part(cls, value: str) -> str:
        if value not in ("any", "morning", "afternoon", "evening"):
            raise ValueError("Franja horaria invalida")
        return value


MAX_WAITLIST_DAYS_AHEAD = 60


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
        "waitlist": None
        if result.waitlist is None
        else {
            "service_id": result.waitlist.service_id,
            "professional_id": result.waitlist.professional_id,
            "day": result.waitlist.day.isoformat(),
            "part_of_day": result.waitlist.part_of_day,
            "label": result.waitlist.label,
        },
        "context": {
            "service_id": result.context.service_id,
            "professional_id": result.context.professional_id,
            "day": result.context.day.isoformat() if result.context.day else None,
        },
        "calendar_days": [d.isoformat() for d in result.calendar_days],
        "selected_day": result.selected_day.isoformat() if result.selected_day else None,
        "selected_time": result.selected_time,
    }


@app.get("/api/slots")
def slots(
    service_id: int,
    day: date,
    professional_id: int | None = None,
    conn=Depends(get_conn),
    now: datetime = Depends(get_now),
) -> dict:
    catalog = flow.load_catalog(conn)
    if service_id not in dict(catalog.services):
        raise HTTPException(400, "Servicio inexistente")
    if professional_id is not None and professional_id not in dict(catalog.professionals):
        raise HTTPException(400, "Profesional inexistente")
    options = flow.options_for_day(conn, catalog, service_id, professional_id, day, "any", None, now)
    return {
        "day": day.isoformat(),
        "options": [
            {
                "professional_id": o.professional_id,
                "professional_name": o.professional_name,
                "start": o.start.isoformat(),
                "label": o.label,
            }
            for o in options
        ],
    }


@app.post("/api/book")
def book(body: BookIn, conn=Depends(get_conn)) -> dict:
    catalog = flow.load_catalog(conn)
    services = dict(catalog.services)
    professionals = dict(catalog.professionals)
    if body.service_id not in services or body.professional_id not in professionals:
        raise HTTPException(400, "Servicio o profesional inexistente")

    customer_id = customers.find_by_phone(conn, body.phone)
    try:
        # El turno se valida antes de crear al cliente, asi un horario ocupado no deja registros sueltos.
        if body.start not in scheduling.free_slots(conn, body.professional_id, body.service_id, body.start.date()):
            raise scheduling.SlotUnavailable(body.start.isoformat())
        if customer_id is None:
            customer_id = customers.create(conn, body.customer_name, body.phone)
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


@app.post("/api/waitlist")
def join_waitlist(body: WaitlistIn, conn=Depends(get_conn), now: datetime = Depends(get_now)) -> dict:
    catalog = flow.load_catalog(conn)
    if body.service_id not in dict(catalog.services) or (
        body.professional_id is not None and body.professional_id not in dict(catalog.professionals)
    ):
        raise HTTPException(400, "Servicio o profesional inexistente")
    if not (now.date() <= body.day <= now.date() + timedelta(days=MAX_WAITLIST_DAYS_AHEAD)):
        raise HTTPException(400, "Elegí un día entre hoy y los próximos 60 días.")

    customer_id = customers.find_by_phone(conn, body.phone) or customers.create(conn, body.customer_name, body.phone)
    try:
        _, created = waitlist.add_entry(
            conn, customer_id, body.service_id, body.professional_id, body.day, body.part_of_day, now
        )
    except waitlist.WaitlistFull:
        raise HTTPException(
            409, f"Ya estás en {waitlist.MAX_WAITING_PER_CUSTOMER} listas de espera. Esperá a que el negocio te contacte."
        )
    label = flow.WaitlistOffer(body.service_id, body.professional_id, body.day, body.part_of_day).label
    prefix = "Listo, te anotamos" if created else "Ya estabas anotado/a"
    return {"created": created, "summary": f"{prefix} para el {label}. Si se libera un lugar, el negocio te va a contactar."}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
def admin_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
