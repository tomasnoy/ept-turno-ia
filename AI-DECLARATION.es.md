---
version: "0.1.2"
level: copilot
processes:
  design: hint
  implementation: copilot
  testing: copilot
  documentation: copilot
  review: assist
  deployment: assist
---

## Notes

- Proyecto final del Curso de Inteligencia Artificial para Programadores (UTN FRBA), desarrollado
  por Tomás con la asistencia de **Claude Code** (Anthropic) como copiloto de programación.
- **Diseño (`hint`)**: las decisiones de arquitectura las tomó el humano — IA interpreta y propone,
  la lógica tradicional valida y guarda; capa de modelo intercambiable (Ollama/Gemini/Anthropic);
  esquema multi-tenant por `business_id`. La IA sugirió alternativas cuando se le consultó, pero no
  decidió por su cuenta.
- **Implementación y tests (`copilot`)**: Claude Code escribió la mayor parte del código y las
  pruebas a partir de esas decisiones. Cada cambio fue revisado y aprobado por el humano antes de
  incorporarse; el autor entiende y puede explicar cada parte del sistema.
- **Documentación (`copilot`)**: el README y otros documentos se redactaron con asistencia de IA y
  fueron revisados por el humano.
- **Revisión (`assist`)**: se usaron pasadas de revisión de código asistidas por IA (incluyendo una
  revisión de seguridad y concurrencia) que señalaron problemas puntuales corregidos manualmente.
  Además de Claude Code, se usó **OpenAI Codex** de forma separada para pasadas de revisión
  orientadas a encontrar errores en el código.
- **Despliegue (`assist`)**: los comandos y la configuración de despliegue en Render fueron
  sugeridos por la IA; el humano cargó los secretos (`ADMIN_TOKEN`, `GEMINI_API_KEY`) y ejecutó las
  acciones sensibles.
- Todos los commits del repositorio son reales y reflejan el avance incremental del proyecto.
- Nota aparte: la aplicación en sí también usa un LLM como parte de su funcionalidad (interpretar
  pedidos de turnos en lenguaje natural), a través de una capa de proveedor intercambiable
  (`app/llm/`: Ollama local, Gemini o Anthropic). Eso es una característica del producto, distinta
  de esta declaración sobre cómo se construyó el código; está documentada en
  [README.md](README.md).
