from app import config
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMProvider
from app.llm.ollama_provider import OllamaProvider


def get_provider() -> LLMProvider:
    if config.LLM_PROVIDER == "ollama":
        return OllamaProvider()
    if config.LLM_PROVIDER == "anthropic":
        return AnthropicProvider()
    raise ValueError(f"LLM_PROVIDER desconocido: {config.LLM_PROVIDER!r}")
