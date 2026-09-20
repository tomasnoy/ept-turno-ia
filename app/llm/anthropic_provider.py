import httpx

from app import config
from app.llm.base import LLMError, LLMProvider


class AnthropicProvider(LLMProvider):
    """Modelo en la nube. Solo recibe el texto del pedido, nunca datos de clientes."""

    def complete(self, system: str, user: str) -> str:
        if not config.ANTHROPIC_API_KEY:
            raise LLMError("Falta ANTHROPIC_API_KEY en el entorno")
        try:
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": config.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": config.ANTHROPIC_MODEL,
                    "max_tokens": 512,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=60,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"Anthropic no respondio: {exc}") from exc
        return resp.json()["content"][0]["text"]
