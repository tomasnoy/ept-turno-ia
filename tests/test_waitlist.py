import sqlite3

import pytest

from app import db
from tests.conftest import CLAVE
from tests.test_api import chat, usar_modelo

HEADERS = {"X-Admin-Token": CLAVE}
SABADO = "2026-09-26"  # atienden ambas profesionales de 09:00 a 14:00


def llenar_sabado():
    """Ocupa todo el sabado de Laura y Martina. Devuelve los ids de los dos turnos."""
    conn = db.connect()
    conn.execute("INSERT INTO customers (id, name, phone) VALUES (100, 'Cliente Ocupado', '11 0000-0000')")
    ids = [
        conn.execute(
            "INSERT INTO appointments (customer_id, professional_id, service_id, start, end) "
            "VALUES (100, ?, 1, ?, ?)",
            (pro, f"{SABADO}T09:00:00", f"{SABADO}T14:00:00"),
        ).lastrowid
        for pro in (1, 2)
    ]
    conn.commit()
    return ids


def anotarse(client, **overrides):
    body = {
        "customer_name": "Lucía Gómez",
        "phone": "11 2222-3333",
        "service_id": 1,
        "day": SABADO,
        "part_of_day": "any",
    }
    body.update(overrides)
    return client.post("/api/waitlist", json=body)


def lista(client):
    return client.get("/api/admin/waitlist", headers=HEADERS).json()["entries"]


# --- Chat: cuando ofrece anotarse -------------------------------------------------------------


def test_chat_ofrece_lista_de_espera_si_el_dia_esta_completo(client):
    llenar_sabado()
    usar_modelo('{"action":"book","service":"Corte de pelo","day":"sabado"}')
    data = chat(client, "un corte el sabado").json()
    assert data["waitlist"]["day"] == SABADO
    assert data["waitlist"]["service_id"] == 1
    assert "sábado 26/09" in data["waitlist"]["label"]
    assert data["options"] and not data["options"][0]["start"].startswith(SABADO)  # alternativas otros dias


def test_chat_ofrece_lista_de_espera_si_no_hay_lugar_en_la_franja(client):
    conn = db.connect()
    conn.execute("INSERT INTO customers (id, name) VALUES (100, 'X')")
    for pro in (1, 2):  # ocupa solo la tarde del viernes
        conn.execute(
            "INSERT INTO appointments (customer_id, professional_id, service_id, start, end) "
            "VALUES (100, ?, 1, '2026-09-25T15:00:00', '2026-09-25T19:00:00')", (pro,))
    conn.commit()
    usar_modelo('{"action":"book","service":"Corte de pelo","day":"viernes","part_of_day":"afternoon"}')
    data = chat(client, "un corte el viernes a la tarde").json()
    assert data["waitlist"]["part_of_day"] == "afternoon"
    assert "a la tarde" in data["waitlist"]["label"]


def test_chat_no_ofrece_lista_si_hay_lugar(client):
    usar_modelo('{"action":"book","service":"Corte de pelo","day":"viernes"}')
    assert chat(client, "un corte el viernes").json()["waitlist"] is None


# --- Anotarse ---------------------------------------------------------------------------------


def test_anotarse_crea_la_entrada_y_reconoce_al_cliente(client):
    resp = anotarse(client)
    assert resp.status_code == 200 and resp.json()["created"] is True
    assert "sábado 26/09" in resp.json()["summary"]
    anotarse(client, day="2026-09-25")  # mismo telefono, otro dia
    assert db.connect().execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 1


def test_anotarse_dos_veces_para_lo_mismo_no_duplica(client):
    anotarse(client)
    segunda = anotarse(client).json()
    assert segunda["created"] is False and "Ya estabas anotado" in segunda["summary"]
    assert len(lista(client)) == 1


def test_limite_de_listas_por_cliente(client):
    for dia in ("2026-09-22", "2026-09-23", "2026-09-24"):
        assert anotarse(client, day=dia).status_code == 200
    assert anotarse(client, day="2026-09-25").status_code == 409


@pytest.mark.parametrize(
    "cambio, estado",
    [
        ({"phone": ""}, 422),  # el telefono es obligatorio
        ({"phone": "<script>"}, 422),
        ({"customer_name": "A"}, 422),
        ({"part_of_day": "medianoche"}, 422),
        ({"service_id": 999}, 400),
        ({"professional_id": 999}, 400),
        ({"day": "2026-09-20"}, 400),  # ya paso
        ({"day": "2026-12-31"}, 400),  # mas de 60 dias
    ],
)
def test_anotarse_valida_los_datos(client, cambio, estado):
    assert anotarse(client, **cambio).status_code == estado


# --- Panel: ver, reacomodar, dar el turno -------------------------------------------------------


def test_panel_de_espera_requiere_clave(client):
    assert client.get("/api/admin/waitlist").status_code == 401
    assert client.post("/api/admin/waitlist/1/remove").status_code == 401
    assert client.post("/api/admin/waitlist/1/book", json={"professional_id": 1, "start": f"{SABADO}T09:00:00"}).status_code == 401


def test_lista_de_espera_por_orden_de_llegada(client):
    llenar_sabado()
    anotarse(client, customer_name="Primera", phone="11 1111-1111")
    anotarse(client, customer_name="Segunda", phone="11 2222-2222")
    entradas = lista(client)
    assert [e["customer"] for e in entradas] == ["Primera", "Segunda"]
    assert entradas[0]["offers"] == []  # sabado completo: nada para ofrecer todavia


def test_cancelar_avisa_a_quien_esta_esperando(client):
    turnos = llenar_sabado()
    anotarse(client, customer_name="Lucía Gómez")
    anotarse(client, customer_name="Otro Dia", phone="11 4444-4444", day="2026-09-25")
    resp = client.post(f"/api/admin/appointments/{turnos[0]}/cancel", headers=HEADERS).json()
    assert [m["customer"] for m in resp["waitlist_matches"]] == ["Lucía Gómez"]  # solo el del dia liberado
    ofertas = lista(client)[0]["offers"]
    assert ofertas and all(o["start"].startswith(SABADO) for o in ofertas)
    assert all(o["professional_id"] == 1 for o in ofertas)  # solo la profesional que quedo libre


def test_cancelar_sin_nadie_esperando_no_devuelve_coincidencias(client):
    turnos = llenar_sabado()
    resp = client.post(f"/api/admin/appointments/{turnos[0]}/cancel", headers=HEADERS).json()
    assert resp["waitlist_matches"] == []


def test_respeta_la_franja_y_el_profesional_pedidos(client):
    turnos = llenar_sabado()
    anotarse(client, customer_name="Quiere Martina", phone="11 5555-5555", professional_id=2)
    client.post(f"/api/admin/appointments/{turnos[0]}/cancel", headers=HEADERS)  # se libera Laura
    assert lista(client)[0]["offers"] == []  # Laura no le sirve
    client.post(f"/api/admin/appointments/{turnos[1]}/cancel", headers=HEADERS)  # se libera Martina
    assert lista(client)[0]["offers"]


def test_dar_el_turno_reserva_y_saca_de_la_lista(client):
    turnos = llenar_sabado()
    anotarse(client)
    client.post(f"/api/admin/appointments/{turnos[0]}/cancel", headers=HEADERS)
    oferta = lista(client)[0]["offers"][0]
    resp = client.post("/api/admin/waitlist/1/book", json=oferta_body(oferta), headers=HEADERS)
    assert resp.status_code == 200
    assert lista(client) == []
    agenda = client.get(f"/api/admin/agenda?day={SABADO}", headers=HEADERS).json()["appointments"]
    assert any(a["customer"] == "Lucía Gómez" and a["status"] == "confirmed" for a in agenda)
    # no se le puede dar dos veces
    assert client.post("/api/admin/waitlist/1/book", json=oferta_body(oferta), headers=HEADERS).status_code == 409


def oferta_body(oferta):
    return {"professional_id": oferta["professional_id"], "start": oferta["start"]}


def test_no_se_puede_dar_un_horario_ocupado_ni_de_otro_dia(client):
    llenar_sabado()
    anotarse(client)
    ocupado = {"professional_id": 1, "start": f"{SABADO}T09:00:00"}
    assert client.post("/api/admin/waitlist/1/book", json=ocupado, headers=HEADERS).status_code == 409
    otro_dia = {"professional_id": 1, "start": "2026-09-25T15:00:00"}
    assert client.post("/api/admin/waitlist/1/book", json=otro_dia, headers=HEADERS).status_code == 409


def test_no_se_le_da_otro_profesional_al_que_pidio_uno(client):
    turnos = llenar_sabado()
    anotarse(client, professional_id=2)
    client.post(f"/api/admin/appointments/{turnos[0]}/cancel", headers=HEADERS)  # libre Laura
    laura = {"professional_id": 1, "start": f"{SABADO}T09:00:00"}
    assert client.post("/api/admin/waitlist/1/book", json=laura, headers=HEADERS).status_code == 409


def test_quitar_de_la_lista(client):
    anotarse(client)
    assert client.post("/api/admin/waitlist/1/remove", headers=HEADERS).status_code == 200
    assert lista(client) == []
    assert client.post("/api/admin/waitlist/1/remove", headers=HEADERS).status_code == 409
    assert client.post("/api/admin/waitlist/999/remove", headers=HEADERS).status_code == 404
    assert anotarse(client).json()["created"] is True  # puede volver a anotarse


def test_entradas_de_dias_pasados_no_se_muestran(client):
    anotarse(client)
    conn = db.connect()
    conn.execute("UPDATE waitlist SET day = '2026-09-10'")
    conn.commit()
    assert lista(client) == []


# --- Migracion de bases viejas -------------------------------------------------------------------


def test_migracion_agrega_columnas_a_una_tabla_vieja():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, phone TEXT);
           CREATE TABLE waitlist (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL,
               service_id INTEGER NOT NULL, professional_id INTEGER, day TEXT NOT NULL);
           INSERT INTO waitlist (customer_id, service_id, day) VALUES (1, 1, '2026-09-26');"""
    )
    db.init_db(conn)
    columnas = {r["name"] for r in conn.execute("PRAGMA table_info(waitlist)")}
    assert {"part_of_day", "status", "created_at"} <= columnas
    fila = conn.execute("SELECT part_of_day, status FROM waitlist").fetchone()
    assert (fila["part_of_day"], fila["status"]) == ("any", "waiting")  # los datos viejos siguen validos
    db.init_db(conn)  # correrlo dos veces no rompe nada
