import httpx
import pytest

from app import config
from app.llm import factory
from app.llm.base import LLMError
from app.llm.gemini_provider import GeminiProvider


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return self.payload


@pytest.fixture
def capturar(monkeypatch):
    """Reemplaza httpx.post y guarda lo que se envio."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "clave-falsa")
    monkeypatch.setattr(config, "GEMINI_MODEL", "gemini-test")
    sent = {}

    def instalar(response):
        def fake_post(url, **kwargs):
            sent.update(url=url, **kwargs)
            return response

        monkeypatch.setattr(httpx, "post", fake_post)
        return sent

    return instalar


def respuesta(texto):
    return FakeResponse({"candidates": [{"content": {"parts": [{"text": texto}]}}]})


def test_gemini_arma_bien_el_pedido(capturar):
    sent = capturar(respuesta('{"action":"other"}'))
    GeminiProvider().complete("sistema", "usuario")
    assert sent["url"].endswith("/models/gemini-test:generateContent")
    assert "clave-falsa" not in sent["url"]  # la key va en el header, no en la URL
    assert sent["headers"] == {"x-goog-api-key": "clave-falsa"}
    body = sent["json"]
    assert body["systemInstruction"]["parts"][0]["text"] == "sistema"
    assert body["contents"][0]["parts"][0]["text"] == "usuario"
    assert body["generationConfig"] == {"temperature": 0, "responseMimeType": "application/json"}


def test_gemini_devuelve_el_texto_y_complete_json_lo_parsea(capturar):
    capturar(respuesta('{"action":"book","day":"viernes"}'))
    assert GeminiProvider().complete_json("s", "u") == {"action": "book", "day": "viernes"}


def test_gemini_ignora_las_partes_de_razonamiento(capturar):
    capturar(FakeResponse({"candidates": [{"content": {"parts": [
        {"text": "pensando...", "thought": True}, {"text": '{"ok":true}'}]}}]}))
    assert GeminiProvider().complete("s", "u") == '{"ok":true}'


def test_gemini_sin_key_falla_con_mensaje_claro(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        GeminiProvider().complete("s", "u")


def test_gemini_error_http_se_convierte_en_llmerror(capturar):
    capturar(FakeResponse({}, status=429))
    with pytest.raises(LLMError):
        GeminiProvider().complete("s", "u")


def test_gemini_sin_candidatos_o_bloqueado_falla(capturar):
    capturar(FakeResponse({}))
    with pytest.raises(LLMError, match="sin candidatos"):
        GeminiProvider().complete("s", "u")
    capturar(FakeResponse({"candidates": [{"finishReason": "SAFETY"}]}))
    with pytest.raises(LLMError, match="SAFETY"):
        GeminiProvider().complete("s", "u")


def test_factory_elige_el_proveedor_segun_la_configuracion(monkeypatch):
    for nombre, clase in [("ollama", "OllamaProvider"), ("anthropic", "AnthropicProvider"), ("gemini", "GeminiProvider")]:
        monkeypatch.setattr(config, "LLM_PROVIDER", nombre)
        assert type(factory.get_provider()).__name__ == clase
    monkeypatch.setattr(config, "LLM_PROVIDER", "otro")
    with pytest.raises(ValueError):
        factory.get_provider()
