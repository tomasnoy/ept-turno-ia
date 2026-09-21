"""Orquestacion de una conversacion de reserva.

Ciclo: el agente interpreta el pedido, el motor de disponibilidad propone horarios reales y el
usuario confirma. Las respuestas al usuario se arman con plantillas, sin IA: son rapidas y
predecibles.
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from app import scheduling
from app.agents.interpreter import WEEKDAYS, Catalog, Intent, interpret, load_catalog
from app.llm.base import LLMProvider

MAX_OPTIONS = 6
MIN_OPTION_GAP = timedelta(minutes=30)
SEARCH_DAYS = 7
PART_RANGES = {
    "morning": (time(0, 0), time(13, 0)),
    "afternoon": (time(13, 0), time(20, 0)),
    "evening": (time(20, 0), time(23, 59)),
}
PART_NAMES = {"morning": "a la mañana", "afternoon": "a la tarde", "evening": "a la noche"}


@dataclass
class Option:
    professional_id: int
    professional_name: str
    start: datetime

    @property
    def label(self) -> str:
        return f"{day_label(self.start.date())} a las {self.start:%H:%M} con {self.professional_name}"


@dataclass
class Context:
    """Lo que ya se entendio del pedido. Viaja en el cliente entre mensajes."""

    service_id: int | None = None
    professional_id: int | None = None
    day: date | None = None


@dataclass
class ChatResult:
    reply: str
    options: list[Option] = field(default_factory=list)
    context: Context = field(default_factory=Context)


def day_label(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day:%d/%m}".replace("miercoles", "miércoles").replace(
        "sabado", "sábado"
    )


def sanitize_context(ctx: Context, catalog: Catalog, today: date) -> Context:
    """El contexto lo manda el cliente, asi que se valida contra el catalogo real."""
    return Context(
        service_id=ctx.service_id if ctx.service_id in {i for i, _ in catalog.services} else None,
        professional_id=ctx.professional_id
        if ctx.professional_id in {i for i, _ in catalog.professionals}
        else None,
        day=ctx.day if ctx.day and ctx.day >= today else None,
    )


def _matches(start: datetime, part: str, exact: time | None) -> bool:
    if exact is not None:
        return True  # se ordenan por cercania a la hora pedida
    if part == "any":
        return True
    low, high = PART_RANGES[part]
    return low <= start.time() < high


def _options_for_day(
    conn, catalog: Catalog, service_id, professional_id, day, part, exact, now
) -> list[Option]:
    professionals = [
        (i, n) for i, n in catalog.professionals if professional_id in (None, i)
    ]
    found: list[Option] = []
    for pid, name in professionals:
        for start in scheduling.free_slots(conn, pid, service_id, day, now=now):
            if _matches(start, part, exact):
                found.append(Option(pid, name, start))
    if exact is not None:
        target = datetime.combine(day, exact)
        found.sort(key=lambda o: (abs(o.start - target), o.professional_id))
        found = sorted(found[: MAX_OPTIONS], key=lambda o: (o.start, o.professional_id))
    else:
        found.sort(key=lambda o: (o.start, o.professional_id))
    unique: dict[datetime, Option] = {}
    for option in found:
        unique.setdefault(option.start, option)  # mismo horario con dos profesionales: uno solo
    options = list(unique.values())
    return options if exact is not None else _spread(options)


def _spread(options: list[Option]) -> list[Option]:
    """Reparte las opciones a lo largo del dia en vez de mostrar seis horarios pegados."""
    spaced: list[Option] = []
    for option in options:
        if not spaced or option.start - spaced[-1].start >= MIN_OPTION_GAP:
            spaced.append(option)
    if len(spaced) <= MAX_OPTIONS:
        return spaced
    last = len(spaced) - 1
    return [spaced[round(i * last / (MAX_OPTIONS - 1))] for i in range(MAX_OPTIONS)]


def find_options(conn, catalog, service_id, professional_id, day, part, exact, now):
    """Devuelve (opciones, nota). Si no hay lugar, relaja la franja y despues busca otros dias."""
    same_day = _options_for_day(conn, catalog, service_id, professional_id, day, part, exact, now)
    if same_day:
        return same_day, ""
    if part != "any":
        relaxed = _options_for_day(conn, catalog, service_id, professional_id, day, "any", exact, now)
        if relaxed:
            return relaxed, f"No queda lugar {PART_NAMES[part]}, pero sí en otros horarios."
    for offset in range(1, SEARCH_DAYS + 1):
        later = day + timedelta(days=offset)
        options = _options_for_day(conn, catalog, service_id, professional_id, later, part, exact, now)
        if not options and part != "any":
            options = _options_for_day(conn, catalog, service_id, professional_id, later, "any", exact, now)
        if options:
            return options, f"El {day_label(day)} no hay lugar. El próximo día con turnos es el {day_label(later)}."
    return [], ""


def handle_message(
    conn: sqlite3.Connection,
    provider: LLMProvider,
    message: str,
    ctx: Context,
    now: datetime,
) -> ChatResult:
    today = now.date()
    catalog = load_catalog(conn)
    ctx = sanitize_context(ctx, catalog, today)
    intent: Intent = interpret(message, catalog, today, provider)

    has_context = any([ctx.service_id, ctx.professional_id, ctx.day])
    extracted = any([intent.service_id, intent.professional_id, intent.day, intent.exact_time])
    if intent.action == "cancel":
        return ChatResult(
            "Para cancelar un turno, comunicate directamente con el negocio. "
            "Si querés reservar uno nuevo, contame qué servicio y para qué día.",
            context=ctx,
        )
    if intent.action != "book" and not (has_context and extracted):
        servicios = ", ".join(name for _, name in catalog.services)
        return ChatResult(
            f"Puedo ayudarte a reservar un turno. Contame qué servicio querés ({servicios}) "
            "y para qué día.",
            context=ctx,
        )

    service_id = intent.service_id or ctx.service_id
    professional_id = intent.professional_id or ctx.professional_id
    day = intent.day or ctx.day
    merged = Context(service_id, professional_id, day)

    if service_id is None:
        servicios = ", ".join(name for _, name in catalog.services)
        return ChatResult(f"¿Qué servicio querés reservar? Tenemos: {servicios}.", context=merged)
    if day is None:
        return ChatResult("¿Para qué día querés el turno?", context=merged)

    options, note = find_options(
        conn, catalog, service_id, professional_id, day, intent.part_of_day, intent.exact_time, now
    )
    if not options:
        return ChatResult(
            f"No encontré horarios en los próximos {SEARCH_DAYS} días. "
            "Probá con otro servicio o profesional.",
            context=merged,
        )
    service = next(n for i, n in catalog.services if i == service_id)
    reply = f"{note} " if note else ""
    reply += f"Estos son los horarios disponibles para {service}. Elegí el que prefieras:"
    return ChatResult(reply.strip(), options, merged)
