from app import config
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMProvider
from app.llm.gemini_provider import GeminiProvider
from app.llm.ollama_provider import OllamaProvider


def get_provider() -> LLMProvider:
    if config.LLM_PROVIDER == "ollama":
        return OllamaProvider()
    if config.LLM_PROVIDER == "anthropic":
        return AnthropicProvider()
    if config.LLM_PROVIDER == "gemini":
        return GeminiProvider()
    raise ValueError(f"LLM_PROVIDER desconocido: {config.LLM_PROVIDER!r}")
