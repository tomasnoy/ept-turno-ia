from datetime import date

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
    assert turno["status"] == "pending"


def test_agenda_no_mezcla_otros_dias(client):
    reservar(client)
    assert agenda(client, "2026-09-24")["appointments"] == []


def test_agenda_sin_dia_usa_hoy(client):
    assert client.get("/api/admin/agenda", headers=HEADERS).json()["day"] == "2026-09-21"


def test_proximos_dias_no_cuentan_cancelados(client):
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


# --- Confirmar turnos ---------------------------------------------------------------------------


def test_confirmar_turno_pendiente(client):
    turno = reservar(client)
    assert agenda(client)["appointments"][0]["status"] == "pending"
    resp = client.post(f"/api/admin/appointments/{turno}/confirm", headers=HEADERS)
    assert resp.status_code == 200 and resp.json()["status"] == "confirmed"
    assert agenda(client)["appointments"][0]["status"] == "confirmed"


def test_no_se_puede_confirmar_dos_veces_ni_lo_cancelado_ni_lo_inexistente(client):
    turno = reservar(client)
    client.post(f"/api/admin/appointments/{turno}/confirm", headers=HEADERS)
    assert client.post(f"/api/admin/appointments/{turno}/confirm", headers=HEADERS).status_code == 409
    assert client.post("/api/admin/appointments/999/confirm", headers=HEADERS).status_code == 404
    otro = reservar(client, "2026-09-25T16:00:00", phone="11 4444-0000")
    client.post(f"/api/admin/appointments/{otro}/cancel", headers=HEADERS)
    assert client.post(f"/api/admin/appointments/{otro}/confirm", headers=HEADERS).status_code == 409


# --- Configuracion: interfaz ---------------------------------------------------------------------


def test_settings_valores_por_defecto_y_actualizacion(client):
    data = client.get("/api/admin/settings", headers=HEADERS).json()
    assert data["business_name"] == "Peluquería Demo"
    resp = client.put(
        "/api/admin/settings",
        json={"business_name": "Nuevo Salón", "welcome_message": "Hola, bienvenido"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json() == {"business_name": "Nuevo Salón", "welcome_message": "Hola, bienvenido"}
    assert client.get("/api/business").json()["name"] == "Nuevo Salón"
    assert client.get("/api/business").json()["welcome_message"] == "Hola, bienvenido"


# --- Configuracion: servicios y profesionales ----------------------------------------------------


def test_crear_y_editar_servicio(client):
    creado = client.post(
        "/api/admin/services", json={"name": "Manicura", "duration_min": 30}, headers=HEADERS
    ).json()
    assert creado["active"] is True
    nombres = {s["name"] for s in client.get("/api/admin/services", headers=HEADERS).json()["services"]}
    assert "Manicura" in nombres

    editado = client.put(
        f"/api/admin/services/{creado['id']}",
        json={"name": "Manicura", "duration_min": 45, "active": False},
        headers=HEADERS,
    ).json()
    assert editado["duration_min"] == 45 and editado["active"] is False
    assert client.put("/api/admin/services/999", json={"name": "XX", "duration_min": 10}, headers=HEADERS).status_code == 404


def test_servicio_desactivado_no_se_ofrece_en_el_chat(client):
    client.put(
        "/api/admin/services/1", json={"name": "Corte de pelo", "duration_min": 45, "active": False}, headers=HEADERS
    )
    nombres = {s["name"] for s in client.get("/api/business").json()["services"]}
    assert "Corte de pelo" not in nombres


def test_crear_y_editar_profesional(client):
    creado = client.post("/api/admin/professionals", json={"name": "Sofía"}, headers=HEADERS).json()
    assert creado["active"] is True
    editado = client.put(
        f"/api/admin/professionals/{creado['id']}", json={"name": "Sofía", "active": False}, headers=HEADERS
    ).json()
    assert editado["active"] is False
    assert client.put("/api/admin/professionals/999", json={"name": "XX"}, headers=HEADERS).status_code == 404


# --- Configuracion: horarios ----------------------------------------------------------------------


def test_configurar_horarios_reemplaza_la_franja_del_dia(client):
    resp = client.put(
        "/api/admin/working-hours",
        json={"professional_id": 1, "weekday": 0, "ranges": [{"start": "10:00", "end": "12:00"}]},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = client.get("/api/admin/working-hours", headers=HEADERS).json()
    lunes_laura = [h for h in data["hours"] if h["professional_id"] == 1 and h["weekday"] == 0]
    assert lunes_laura == [{"professional_id": 1, "weekday": 0, "start": "10:00", "end": "12:00"}]


def test_horarios_validan_formato_y_superposicion(client):
    malformado = client.put(
        "/api/admin/working-hours",
        json={"professional_id": 1, "weekday": 0, "ranges": [{"start": "10h", "end": "12:00"}]},
        headers=HEADERS,
    )
    assert malformado.status_code == 422
    invertido = client.put(
        "/api/admin/working-hours",
        json={"professional_id": 1, "weekday": 0, "ranges": [{"start": "12:00", "end": "10:00"}]},
        headers=HEADERS,
    )
    assert invertido.status_code == 422
    superpuesto = client.put(
        "/api/admin/working-hours",
        json={
            "professional_id": 1,
            "weekday": 0,
            "ranges": [{"start": "09:00", "end": "13:00"}, {"start": "12:00", "end": "15:00"}],
        },
        headers=HEADERS,
    )
    assert superpuesto.status_code == 422
    assert client.put(
        "/api/admin/working-hours",
        json={"professional_id": 999, "weekday": 0, "ranges": []},
        headers=HEADERS,
    ).status_code == 404


def test_vaciar_los_horarios_deja_el_dia_sin_turnos(client):
    client.put(
        "/api/admin/working-hours",
        json={"professional_id": 1, "weekday": 0, "ranges": []},
        headers=HEADERS,
    )
    from app import db, scheduling

    conn = db.connect()
    assert scheduling.free_slots(conn, 1, 1, date(2026, 9, 21)) == []
