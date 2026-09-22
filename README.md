# Gestor de turnos con IA

SaaS multi-negocio de gestión de turnos para negocios chicos que trabajan con reserva
(peluquerías, consultorios de belleza, pilates, etc.). Cada negocio se registra con su propia
cuenta, personaliza su página (nombre, logo, color) y gestiona su agenda desde su panel. Sus
clientes piden el turno en lenguaje natural y el sistema propone horarios disponibles.

> Proyecto final del Curso de Inteligencia Artificial para Programadores, UTN FRBA. En desarrollo.

## Idea de arquitectura

- **La IA interpreta y propone; la lógica tradicional valida y guarda.** Ningún turno se escribe sin
  pasar por el motor de disponibilidad (`app/scheduling.py`), así una alucinación del modelo no puede
  generar turnos superpuestos.
- **Modelo intercambiable** (`app/llm/`): Ollama (local, los datos no salen del equipo), Gemini o
  Anthropic (nube, reciben solo el texto del pedido, nunca datos de clientes). Se elige con
  `LLM_PROVIDER`. En producción se usa Gemini (`gemini-3.5-flash-lite`).
- **Multi-tenant**: todas las tablas (servicios, profesionales, horarios, turnos, lista de espera)
  cuelgan de un `business_id`. Cada negocio tiene su propio login (email + clave) y su propia sesión;
  ninguna consulta cruza datos entre negocios (`app/tenancy.py`, `app/auth.py`).
- **Memoria persistente** en SQLite: negocios, clientes, turnos, lista de espera.

## Cómo correrlo

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # en Linux/Mac: .venv/bin/pip
cp .env.example .env                            # y completar lo que corresponda
.venv/Scripts/python -m pytest                  # tests
.venv/Scripts/uvicorn app.main:app --reload     # servidor
```

## Estado

- [x] Esquema de base de datos y motor de disponibilidad, con tests
- [x] Capa de proveedores de IA (Ollama / Gemini / Anthropic)
- [x] Agente de interpretación de pedidos (`app/agents/interpreter.py`)
- [x] API y chat de reserva (`app/main.py`, `app/flow.py`, `static/index.html`)
- [x] Panel del negocio: agenda por día, turnos pendientes/confirmar/cancelar, filtros (`/admin`)
- [x] Lista de espera y reacomodo ante cancelaciones (`app/waitlist.py`)
- [x] SaaS multi-negocio: registro, login propio, marca y planes (`app/tenancy.py`, `app/accounts.py`)
- [x] Despliegue en Render (https://ept-turno-ia.onrender.com)

## Rutas principales

- `/` — landing del SaaS, con los planes.
- `/registro` — alta de un negocio nuevo (nombre, email, clave, plan).
- `/admin` — login del negocio (email + clave) y panel: agenda, turnos pendientes de confirmar,
  lista de espera, y Configuración (marca, plan, servicios, profesionales, horarios).
- `/b/{slug}` — página de reserva de un negocio puntual (la que se comparte con sus clientes).

## Planes

Se diferencian por cantidad de profesionales. Cambiar de plan en esta demo no procesa ningún
cobro real (no hay integración con una pasarela de pago).

| Plan    | Profesionales | Precio (demo) |
|---------|---------------|---------------|
| Básico  | 1             | Gratis        |
| Pro     | 5             | $9.990/mes    |
| Premium | Ilimitados    | $19.990/mes   |

## Panel del negocio

Ruta `/admin`. Cada negocio ingresa con su email y clave (creados en `/registro`), y ve solo su
propia agenda: reservas por día, filtro por profesional, turnos pendientes de confirmar o
cancelar. Tras 10 intentos de login fallidos se bloquea temporalmente el acceso por IP.
Los turnos que reserva un cliente desde el chat nacen `pending`: el negocio los confirma (o
cancela) desde el panel antes de que cuenten como definitivos.

## Lista de espera y reacomodo

Si el cliente no encuentra lugar (ese día o esa franja), el chat le ofrece anotarse con nombre y
teléfono. Cuando el negocio cancela un turno, el panel avisa a quién se le puede ofrecer ese lugar
(por orden de llegada, respetando el día, la franja y el profesional que pidió), le muestra los
horarios que hoy le sirven y permite asignarle el turno con un clic. La decisión es lógica
determinista: los datos de los clientes no pasan por el modelo de IA.

## Producción

- Aplicación: https://ept-turno-ia.onrender.com (landing) — cada negocio se registra en `/registro`
  y gestiona su agenda en `/admin`.
- Hosting: Render, plan gratuito, región Virginia. Despliegue automático en cada push a `main`.
- Variables de entorno en Render: `LLM_PROVIDER=gemini`, `TIMEZONE`,
  `FORWARDED_ALLOW_IPS=*` (detrás del proxy de Render, para identificar a cada visitante), y el
  secreto `GEMINI_API_KEY`, cargado solo en el panel de Render. `BUSINESS_NAME` y `ADMIN_TOKEN`
  quedan como variables heredadas del proyecto pre-SaaS (single-tenant): solo se usan si la base
  ya tenía datos de esa época, para no perderlos al migrar.
- Limitaciones del plan gratuito: la app se duerme tras unos minutos sin uso (la primera visita
  tarda en despertar) y el disco es efímero, por lo que la base SQLite (negocios, turnos, etc.) se
  recrea desde cero —con un negocio demo de ejemplo— en cada reinicio o despliegue.
- Privacidad del modelo en la nube: en el nivel gratuito de Gemini, Google puede usar el contenido
  enviado para mejorar sus productos. Por eso al modelo solo viaja el texto del pedido; nombre y
  teléfono del cliente nunca salen del servidor.
