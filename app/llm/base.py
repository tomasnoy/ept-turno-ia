import json
import re
from abc import ABC, abstractmethod


class LLMError(Exception):
    pass


class LLMProvider(ABC):
    """Interfaz unica para el modelo de IA. Permite cambiar entre local y nube sin tocar los agentes."""

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Devuelve el texto crudo de la respuesta del modelo."""

    def complete_json(self, system: str, user: str) -> dict:
        raw = self.complete(system, user)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match is None:
            raise LLMError(f"El modelo no devolvio JSON: {raw[:200]!r}")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMError(f"JSON invalido del modelo: {exc}") from exc
