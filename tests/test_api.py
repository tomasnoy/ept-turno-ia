from app import main
from app.llm.base import LLMError, LLMProvider


class FakeProvider(LLMProvider):
    def __init__(self, response: str = '{"action":"other"}'):
        self.response = response

    def complete(self, system: str, user: str) -> str:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def usar_modelo(response):
    main.app.dependency_overrides[main.get_llm] = lambda: FakeProvider(response)


def chat(client, message, context=None):
    return client.post(f"/api/b/{client.slug}/chat", json={"message": message, "context": context or {}})


def test_business_devuelve_catalogo(client):
    data = client.get(f"/api/b/{client.slug}/business").json()
    assert {s["name"] for s in data["services"]} == {"Corte de pelo", "Tintura", "Peinado"}
    assert len(data["professionals"]) == 2


def test_pedido_completo_devuelve_horarios_de_la_tarde(client):
    usar_modelo('{"action":"book","service":"Corte de pelo","professional":"Laura","day":"viernes","part_of_day":"afternoon"}')
    data = chat(client, "quiero un corte con Laura el viernes a la tarde").json()
    assert data["options"]
    assert all(o["professional_name"] == "Laura" for o in data["options"])
    horas = [int(o["start"][11:13]) for o in data["options"]]
    assert all(h >= 15 for h in horas)  # solo la tarde
    assert horas[-1] - horas[0] >= 2  # repartidas, no seis horarios pegados
    assert data["context"] == {"service_id": 1, "professional_id": 1, "day": "2026-09-25"}


def test_sin_dia_repregunta_y_conserva_el_servicio(client):
    usar_modelo('{"action":"book","service":"Tintura","day":null}')
    data = chat(client, "quiero una tintura").json()
    assert data["options"] == []
    assert "día" in data["reply"]
    assert data["context"]["service_id"] == 2


def test_respuesta_de_seguimiento_completa_con_el_contexto(client):
    usar_modelo('{"action":"other","day":"martes"}')
    data = chat(client, "el martes", {"service_id": 2}).json()
    assert data["options"]
    assert data["context"]["service_id"] == 2
    assert data["context"]["day"] == "2026-09-22"


def test_mensaje_fuera_de_tema_explica_que_puede_hacer(client):
    usar_modelo('{"action":"other"}')
    data = chat(client, "que hora es en tokio").json()
    assert data["options"] == []
    assert "Corte de pelo" in data["reply"]


def test_dia_sin_atencion_ofrece_el_proximo_dia(client):
    usar_modelo('{"action":"book","service":"Corte de pelo","day":"domingo"}')
    data = chat(client, "un corte el domingo").json()
    assert data["options"][0]["start"].startswith("2026-09-28")  # el domingo 27 se salta
    assert "próximo día" in data["reply"]


def test_falla_del_modelo_devuelve_503_amigable(client):
    usar_modelo(LLMError("caido"))
    resp = chat(client, "quiero un turno")
    assert resp.status_code == 503
    assert "Probá de nuevo" in resp.json()["detail"]


def test_contexto_manipulado_se_ignora(client):
    usar_modelo('{"action":"book","service":"Tintura","day":"hoy"}')
    data = chat(client, "tintura hoy", {"service_id": 999, "professional_id": 999, "day": "2000-01-01"}).json()
    assert data["context"]["professional_id"] is None


def test_mensaje_vacio_o_enorme_se_rechaza(client):
    assert chat(client, "").status_code == 422
    assert chat(client, "a" * 1001).status_code == 422


def reservar(client, **overrides):
    body = {
        "customer_name": "Ana Pérez",
        "phone": "11 5555-1234",
        "professional_id": 1,
        "service_id": 1,
        "start": "2026-09-25T15:00:00",
    }
    body.update(overrides)
    return client.post(f"/api/b/{client.slug}/book", json=body)


def test_reserva_queda_pendiente_y_bloquea_el_horario(client):
    resp = reservar(client)
    assert resp.status_code == 200
    assert "pendiente" in resp.json()["summary"]
    assert reservar(client, customer_name="Otra Persona", phone="11 4444-0000").status_code == 409


def test_cliente_repetido_por_telefono_no_se_duplica(client):
    reservar(client, start="2026-09-25T15:00:00")
    reservar(client, start="2026-09-25T16:00:00")
    from app import db

    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 1


def test_horario_ocupado_no_deja_clientes_sueltos(client):
    reservar(client)
    reservar(client, customer_name="Otra Persona", phone="11 4444-0000")
    from app import db

    assert db.connect().execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 1


def test_reserva_fuera_de_horario_es_conflicto(client):
    assert reservar(client, start="2026-09-25T23:00:00").status_code == 409


def test_reserva_valida_datos_de_entrada(client):
    assert reservar(client, customer_name="A").status_code == 422
    assert reservar(client, phone="<script>alert(1)</script>").status_code == 422
    assert reservar(client, professional_id=999).status_code == 400


def test_pagina_principal_se_sirve(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
