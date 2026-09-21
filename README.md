# Gestor de turnos con IA

Aplicación de gestión de turnos para negocios chicos que trabajan con reserva (peluquerías,
consultorios de belleza, pilates, etc.). El cliente pide su turno en lenguaje natural y el sistema
propone horarios disponibles.

> Proyecto final del Curso de Inteligencia Artificial para Programadores, UTN FRBA. En desarrollo.

## Idea de arquitectura

- **La IA interpreta y propone; la lógica tradicional valida y guarda.** Ningún turno se escribe sin
  pasar por el motor de disponibilidad (`app/scheduling.py`), así una alucinación del modelo no puede
  generar turnos superpuestos.
- **Modelo intercambiable** (`app/llm/`): Ollama (local, los datos no salen del equipo), Gemini o
  Anthropic (nube, reciben solo el texto del pedido, nunca datos de clientes). Se elige con
  `LLM_PROVIDER`. En producción se usa Gemini (`gemini-3.5-flash-lite`).
- **Memoria persistente** en SQLite: clientes, turnos, lista de espera.

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
- [x] Panel del negocio: agenda por día, filtros y cancelación (`/admin`, protegido con clave)
- [ ] Lista de espera y reacomodo ante cancelaciones
- [x] Despliegue en Render (https://ept-turno-ia.onrender.com)

## Panel del negocio

Ruta `/admin`. Muestra las reservas por día, permite filtrar por profesional y cancelar turnos.
Se protege con una clave compartida: hay que definir `ADMIN_TOKEN` en el `.env` del servidor.
Si no está definida, el panel queda deshabilitado (nunca abierto por omisión). Tras 10 intentos
fallidos se bloquea temporalmente el acceso.

## Producción

- Aplicación: https://ept-turno-ia.onrender.com (chat de reserva) y `/admin` (panel del negocio)
- Hosting: Render, plan gratuito, región Virginia. Despliegue automático en cada push a `main`.
- Variables de entorno en Render: `LLM_PROVIDER=gemini`, `TIMEZONE`, `BUSINESS_NAME`,
  `FORWARDED_ALLOW_IPS=*` (detrás del proxy de Render, para identificar a cada visitante), y los
  secretos `ANTHROPIC_API_KEY` y `ADMIN_TOKEN`, cargados solo en el panel de Render.
- Limitaciones del plan gratuito: la app se duerme tras unos minutos sin uso (la primera visita
  tarda en despertar) y el disco es efímero, por lo que la base SQLite se recrea con datos de
  ejemplo en cada reinicio o despliegue.
- Privacidad del modelo en la nube: en el nivel gratuito de Gemini, Google puede usar el contenido
  enviado para mejorar sus productos. Por eso al modelo solo viaja el texto del pedido; nombre y
  teléfono del cliente nunca salen del servidor.
