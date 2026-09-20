# Gestor de turnos con IA

Aplicación de gestión de turnos para negocios chicos que trabajan con reserva (peluquerías,
consultorios de belleza, pilates, etc.). El cliente pide su turno en lenguaje natural y el sistema
propone horarios disponibles.

> Proyecto final del Curso de Inteligencia Artificial para Programadores, UTN FRBA. En desarrollo.

## Idea de arquitectura

- **La IA interpreta y propone; la lógica tradicional valida y guarda.** Ningún turno se escribe sin
  pasar por el motor de disponibilidad (`app/scheduling.py`), así una alucinación del modelo no puede
  generar turnos superpuestos.
- **Modelo intercambiable** (`app/llm/`): Ollama (local, los datos no salen del equipo) o Anthropic
  (nube, recibe solo el texto del pedido, nunca datos de clientes). Se elige con `LLM_PROVIDER`.
- **Memoria persistente** en SQLite: clientes, turnos, lista de espera.

## Cómo correrlo

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # en Linux/Mac: .venv/bin/pip
cp .env.example .env                            # y completar lo que corresponda
.venv/Scripts/python -m pytest                  # tests
.venv/Scripts/uvicorn app.main:app --reload     # servidor
```

## Estado

- [x] Esquema de base de datos y motor de disponibilidad, con tests
- [x] Capa de proveedores de IA (Ollama / Anthropic)
- [x] Agente de interpretación de pedidos (`app/agents/interpreter.py`)
- [ ] API y chat de reserva
- [ ] Agente de reacomodo ante cancelaciones
- [ ] Despliegue
