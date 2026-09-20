import httpx

from app import config
from app.llm.base import LLMError, LLMProvider


class OllamaProvider(LLMProvider):
    """Modelo local: los datos no salen del equipo."""

    def complete(self, system: str, user: str) -> str:
        try:
            resp = httpx.post(
                f"{config.OLLAMA_URL}/api/chat",
                json={
                    "model": config.OLLAMA_MODEL,
                    "stream": False,
                    "format": "json",
                    "keep_alive": "30m",
                    "options": {"temperature": 0, "num_ctx": 2048},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=120,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama no respondio: {exc}") from exc
        return resp.json()["message"]["content"]
