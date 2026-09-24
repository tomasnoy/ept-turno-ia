import httpx

from app import config
from app.llm.base import LLMError, LLMProvider

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider(LLMProvider):
    """Modelo en la nube (Google). Solo recibe el texto del pedido, nunca datos de clientes.

    En el nivel gratuito Google puede usar el contenido para mejorar sus productos.
    """

    def complete(self, system: str, user: str) -> str:
        if not config.GEMINI_API_KEY:
            raise LLMError("Falta GEMINI_API_KEY en el entorno")
        try:
            resp = httpx.post(
                URL.format(model=config.GEMINI_MODEL),
                headers={"x-goog-api-key": config.GEMINI_API_KEY},  # en header, no en la URL
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
                },
                timeout=10,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"Gemini no respondio: {exc}") from exc

        candidates = resp.json().get("candidates") or []
        parts = (candidates[0].get("content") or {}).get("parts") if candidates else None
        text = "".join(p.get("text", "") for p in parts or [] if not p.get("thought"))
        if not text:
            reason = candidates[0].get("finishReason", "sin candidatos") if candidates else "sin candidatos"
            raise LLMError(f"Gemini no devolvio texto ({reason})")
        return text
