from datetime import date, time

import pytest

from app.agents.interpreter import MAX_MESSAGE_CHARS, Catalog, interpret
from app.llm.base import LLMProvider

JUEVES = date(2026, 9, 17)  # weekday() == 3
CATALOGO = Catalog(
    services=[(1, "Corte de pelo"), (2, "Tintura")],
    professionals=[(1, "Laura"), (2, "María")],
)


class FakeProvider(LLMProvider):
    """Devuelve una respuesta fija y guarda lo que recibio, sin usar red."""

    def __init__(self, response: str):
        self.response = response
        self.last_system = ""
        self.last_user = ""

    def complete(self, system: str, user: str) -> str:
        self.last_system, self.last_user = system, user
        return self.response


def run(response: str, message: str = "quiero un turno", today: date = JUEVES):
    provider = FakeProvider(response)
    return interpret(message, CATALOGO, today, provider), provider


def test_pedido_completo():
    intent, _ = run(
        '{"action":"book","service":"corte de pelo","professional":"Laura",'
        '"day":"viernes","part_of_day":"afternoon","time":null}',
        message="quiero un corte de pelo con Laura el viernes a la tarde",
    )
    assert intent.action == "book"
    assert (intent.service_id, intent.professional_id) == (1, 1)
    assert intent.day == date(2026, 9, 18)
    assert intent.part_of_day == "afternoon"
    assert intent.missing == []


def test_mismo_dia_de_la_semana_es_el_proximo():
    intent, _ = run('{"action":"book","service":"Tintura","day":"jueves"}', message="tintura el jueves")
    assert intent.day == date(2026, 9, 24)


def test_hoy_y_manana():
    assert run('{"action":"book","service":"Tintura","day":"hoy"}', message="tintura hoy")[0].day == JUEVES
    manana = run('{"action":"book","service":"Tintura","day":"manana"}', message="tintura mañana")[0]
    assert manana.day == date(2026, 9, 18)


def test_profesional_sin_tildes_ni_mayusculas():
    intent, _ = run(
        '{"action":"book","service":"Tintura","professional":"maria","day":"hoy"}',
        message="tintura hoy con MARIA",
    )
    assert intent.professional_id == 2


def test_servicio_inventado_queda_como_faltante():
    intent, _ = run('{"action":"book","service":"Masaje thai","day":"hoy"}', message="masaje thai hoy")
    assert intent.service_id is None
    assert intent.missing == ["service"]


def test_sin_dia_queda_como_faltante():
    intent, _ = run('{"action":"book","service":"Tintura","day":null}')
    assert intent.missing == ["day"]


def test_accion_no_permitida_se_convierte_en_other():
    intent, _ = run('{"action":"delete_all_appointments","service":null,"day":null}')
    assert intent.action == "other"
    assert intent.missing == []


def test_fecha_iso_pasada_se_descarta():
    intent, _ = run('{"action":"book","service":"Tintura","day":"2020-01-01"}', message="tintura el 2020-01-01")
    assert intent.day is None


def test_fecha_y_hora_invalidas_no_rompen():
    intent, _ = run(
        '{"action":"book","service":"Tintura","day":"31 de febrero","time":"tarde"}',
        message="tintura el 31 de febrero",
    )
    assert intent.day is None
    assert intent.exact_time is None


def test_hora_exacta():
    intent, _ = run(
        '{"action":"book","service":"Tintura","day":"hoy","part_of_day":"afternoon","time":"15:30"}',
        message="quiero tintura hoy a las 15:30",
    )
    assert intent.exact_time == time(15, 30)
    assert intent.part_of_day == "any"  # la hora exacta manda sobre la franja


def test_hora_inventada_por_el_modelo_se_descarta():
    intent, _ = run(
        '{"action":"book","service":"Tintura","day":"viernes","time":"14:00"}',
        message="quiero tintura el viernes a la tarde",
    )
    assert intent.exact_time is None


def test_valores_de_tipo_incorrecto_no_rompen():
    intent, _ = run('{"action":"book","service":123,"professional":["x"],"day":5,"part_of_day":9}')
    assert intent.service_id is None
    assert intent.day is None
    assert intent.part_of_day == "any"


def test_mensaje_se_recorta_y_va_delimitado():
    largo = "a" * (MAX_MESSAGE_CHARS + 300)
    _, provider = run('{"action":"other"}', message=largo)
    assert provider.last_user == f"<pedido>{'a' * MAX_MESSAGE_CHARS}</pedido>"


def test_prompt_incluye_catalogo_y_fecha_de_hoy():
    _, provider = run('{"action":"other"}')
    assert "Corte de pelo" in provider.last_system
    assert "Laura" in provider.last_system
    assert "2026-09-17" in provider.last_system


def test_respuesta_sin_json_levanta_error():
    from app.llm.base import LLMError

    with pytest.raises(LLMError):
        run("no se")


def test_profesional_inventado_por_el_modelo_se_descarta():
    intent, _ = run(
        '{"action":"book","service":"Tintura","professional":"Martina","day":"hoy"}',
        message="necesito tintura hoy",
    )
    assert intent.professional_id is None


def test_dia_inventado_por_el_modelo_se_descarta():
    intent, _ = run(
        '{"action":"book","service":"Corte de pelo","day":"domingo"}',
        message="cuanto sale un corte?",
    )
    assert intent.day is None
    assert intent.missing == ["day"]
