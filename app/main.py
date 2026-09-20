from fastapi import FastAPI

from app import config

app = FastAPI(title="Gestor de turnos con IA")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_provider": config.LLM_PROVIDER}
