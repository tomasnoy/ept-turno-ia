from app import auth, config
from tests.conftest import CLAVE

HEADERS = {"X-Admin-Token": CLAVE}


def reservar(client, start="2026-09-25T15:00:00", name="Ana Pérez", phone="11 5555-1234", professional_id=1):
    resp = client.post(
        "/api/book",
        json={"customer_name": name, "phone": phone, "professional_id": professional_id, "service_id": 1, "start": start},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["appointment_id"]


def agenda(client, day="2026-09-25"):
    return client.get(f"/api/admin/agenda?day={day}", headers=HEADERS).json()


def test_sin_clave_no_hay_acceso(client):
    assert client.get("/api/admin/agenda").status_code == 401
    assert client.get("/api/admin/agenda", headers={"X-Admin-Token": "otra"}).status_code == 401
    assert client.post("/api/admin/appointments/1/cancel").status_code == 401


def test_clave_no_configurada_deshabilita_el_panel(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "")
    assert client.get("/api/admin/agenda", headers={"X-Admin-Token": ""}).status_code == 503
    assert client.get("/api/admin/agenda").status_code == 503


def test_check_valida_la_clave(client):
    assert client.get("/api/admin/check", headers=HEADERS).status_code == 200


def test_agenda_muestra_las_reservas_del_dia(client):
    reservar(client, "2026-09-25T16:00:00", name="Zoe", phone="11 4444-0000")
    reservar(client, "2026-09-25T15:00:00")
    data = agenda(client)
    assert [a["customer"] for a in data["appointments"]] == ["Ana Pérez", "Zoe"]  # ordenadas por hora
    turno = data["appointments"][0]
    assert turno["service"] == "Corte de pelo"
    assert turno["professional"] == "Laura"
    assert turno["phone"] == "11 5555-1234"
    assert turno["status"] == "confirmed"


def test_agenda_no_mezcla_otros_dias(client):
    reservar(client)
    assert agenda(client, "2026-09-24")["appointments"] == []


def test_agenda_sin_dia_usa_hoy(client):
    assert client.get("/api/admin/agenda", headers=HEADERS).json()["day"] == "2026-09-21"


def test_proximos_dias_cuentan_solo_confirmados(client):
    a = reservar(client, "2026-09-25T15:00:00")
    reservar(client, "2026-09-25T16:00:00", phone="11 4444-0000")
    client.post(f"/api/admin/appointments/{a}/cancel", headers=HEADERS)
    upcoming = {d["day"]: d["count"] for d in agenda(client)["upcoming"]}
    assert len(upcoming) == 14
    assert upcoming["2026-09-21"] == 0
    assert upcoming["2026-09-25"] == 1


def test_cancelar_libera_el_horario_y_queda_registrado(client):
    turno = reservar(client)
    assert client.post(f"/api/admin/appointments/{turno}/cancel", headers=HEADERS).status_code == 200
    assert agenda(client)["appointments"][0]["status"] == "cancelled"
    reservar(client, name="Otra Persona", phone="11 3333-0000")  # el horario volvio a estar libre


def test_cancelar_dos_veces_o_inexistente(client):
    turno = reservar(client)
    client.post(f"/api/admin/appointments/{turno}/cancel", headers=HEADERS)
    assert client.post(f"/api/admin/appointments/{turno}/cancel", headers=HEADERS).status_code == 409
    assert client.post("/api/admin/appointments/999/cancel", headers=HEADERS).status_code == 404


def test_fecha_invalida_se_rechaza(client):
    assert client.get("/api/admin/agenda?day=mañana", headers=HEADERS).status_code == 422


def test_demasiados_intentos_fallidos_bloquean_incluso_la_clave_correcta(client):
    for _ in range(auth.MAX_FAILURES):
        assert client.get("/api/admin/check", headers={"X-Admin-Token": "mal"}).status_code == 401
    assert client.get("/api/admin/check", headers={"X-Admin-Token": "mal"}).status_code == 429
    assert client.get("/api/admin/check", headers=HEADERS).status_code == 429


def test_pagina_del_panel_se_sirve_sin_datos(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Ana" not in resp.text
