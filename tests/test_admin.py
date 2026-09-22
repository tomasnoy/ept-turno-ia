from datetime import date

from app import auth


def reservar(client, start="2026-09-25T15:00:00", name="Ana Pérez", phone="11 5555-1234", professional_id=1):
    resp = client.post(
        f"/api/b/{client.slug}/book",
        json={"customer_name": name, "phone": phone, "professional_id": professional_id, "service_id": 1, "start": start},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["appointment_id"]


def agenda(client, day="2026-09-25"):
    return client.get(f"/api/admin/agenda?day={day}", headers=client.admin_headers).json()


def test_sin_sesion_no_hay_acceso(client):
    assert client.get("/api/admin/agenda").status_code == 401
    assert client.get("/api/admin/agenda", headers={"X-Session-Token": "invalido"}).status_code == 401
    assert client.post("/api/admin/appointments/1/cancel").status_code == 401


def test_sesion_vencida_no_sirve(client):
    from app import db

    conn = db.connect()
    conn.execute(
        "INSERT INTO sessions (token, business_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        ("vencido", 1, "2026-01-01T00:00:00", "2026-01-02T00:00:00"),
    )
    conn.commit()
    assert client.get("/api/admin/agenda", headers={"X-Session-Token": "vencido"}).status_code == 401


def test_check_valida_la_sesion(client):
    assert client.get("/api/admin/check", headers=client.admin_headers).status_code == 200


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
    assert client.get("/api/admin/agenda", headers=client.admin_headers).json()["day"] == "2026-09-21"


def test_proximos_dias_no_cuentan_cancelados(client):
    a = reservar(client, "2026-09-25T15:00:00")
    reservar(client, "2026-09-25T16:00:00", phone="11 4444-0000")
    client.post(f"/api/admin/appointments/{a}/cancel", headers=client.admin_headers)
    upcoming = {d["day"]: d["count"] for d in agenda(client)["upcoming"]}
    assert len(upcoming) == 14
    assert upcoming["2026-09-21"] == 0
    assert upcoming["2026-09-25"] == 1


def test_cancelar_libera_el_horario_y_queda_registrado(client):
    turno = reservar(client)
    assert client.post(f"/api/admin/appointments/{turno}/cancel", headers=client.admin_headers).status_code == 200
    assert agenda(client)["appointments"][0]["status"] == "cancelled"
    reservar(client, name="Otra Persona", phone="11 3333-0000")  # el horario volvio a estar libre


def test_cancelar_dos_veces_o_inexistente(client):
    turno = reservar(client)
    client.post(f"/api/admin/appointments/{turno}/cancel", headers=client.admin_headers)
    assert client.post(f"/api/admin/appointments/{turno}/cancel", headers=client.admin_headers).status_code == 409
    assert client.post("/api/admin/appointments/999/cancel", headers=client.admin_headers).status_code == 404


def test_fecha_invalida_se_rechaza(client):
    assert client.get("/api/admin/agenda?day=mañana", headers=client.admin_headers).status_code == 422


def test_demasiados_intentos_fallidos_bloquean_incluso_la_clave_correcta(client):
    from app.seed import DEMO_EMAIL, DEMO_PASSWORD

    for _ in range(auth.MAX_FAILURES):
        assert client.post("/api/login", json={"email": DEMO_EMAIL, "password": "mal"}).status_code == 401
    assert client.post("/api/login", json={"email": DEMO_EMAIL, "password": "mal"}).status_code == 429
    assert client.post("/api/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}).status_code == 429


def test_pagina_del_panel_se_sirve_sin_datos(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Ana" not in resp.text


# --- Confirmar turnos ---------------------------------------------------------------------------


def test_confirmar_turno_pendiente(client):
    turno = reservar(client)
    assert agenda(client)["appointments"][0]["status"] == "pending"
    resp = client.post(f"/api/admin/appointments/{turno}/confirm", headers=client.admin_headers)
    assert resp.status_code == 200 and resp.json()["status"] == "confirmed"
    assert agenda(client)["appointments"][0]["status"] == "confirmed"


def test_no_se_puede_confirmar_dos_veces_ni_lo_cancelado_ni_lo_inexistente(client):
    turno = reservar(client)
    client.post(f"/api/admin/appointments/{turno}/confirm", headers=client.admin_headers)
    assert client.post(f"/api/admin/appointments/{turno}/confirm", headers=client.admin_headers).status_code == 409
    assert client.post("/api/admin/appointments/999/confirm", headers=client.admin_headers).status_code == 404
    otro = reservar(client, "2026-09-25T16:00:00", phone="11 4444-0000")
    client.post(f"/api/admin/appointments/{otro}/cancel", headers=client.admin_headers)
    assert client.post(f"/api/admin/appointments/{otro}/confirm", headers=client.admin_headers).status_code == 409


# --- Configuracion: marca del negocio --------------------------------------------------------------


def test_marca_valores_por_defecto_y_actualizacion(client):
    data = client.get("/api/admin/business", headers=client.admin_headers).json()
    assert data["name"] == "Peluquería Demo"
    resp = client.put(
        "/api/admin/business",
        json={"name": "Nuevo Salón", "welcome_message": "Hola, bienvenido", "logo_url": "https://x.com/l.png", "color_primary": "#123456"},
        headers=client.admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Nuevo Salón" and body["welcome_message"] == "Hola, bienvenido"
    assert body["logo_url"] == "https://x.com/l.png" and body["color_primary"] == "#123456"
    public = client.get(f"/api/b/{client.slug}/business").json()
    assert public["name"] == "Nuevo Salón" and public["welcome_message"] == "Hola, bienvenido"


def test_color_invalido_se_rechaza(client):
    resp = client.put(
        "/api/admin/business", json={"name": "X", "color_primary": "rojo"}, headers=client.admin_headers
    )
    assert resp.status_code == 422


# --- Configuracion: plan y limite de profesionales -------------------------------------------------


def test_cambiar_de_plan(client):
    resp = client.put("/api/admin/plan", json={"plan": "pro"}, headers=client.admin_headers)
    assert resp.status_code == 200 and resp.json()["plan"] == "pro"
    assert resp.json()["professional_limit"] == 5


def test_plan_invalido_se_rechaza(client):
    assert client.put("/api/admin/plan", json={"plan": "platino"}, headers=client.admin_headers).status_code == 422


def test_no_se_puede_bajar_de_plan_si_sobran_profesionales(client):
    client.put("/api/admin/plan", json={"plan": "pro"}, headers=client.admin_headers)
    for i in range(4):
        client.post("/api/admin/professionals", json={"name": f"Pro {i}"}, headers=client.admin_headers)
    # ya son 6 (Laura, Martina + 4 nuevos): pro permite 5
    assert client.put("/api/admin/plan", json={"plan": "pro"}, headers=client.admin_headers).status_code == 200
    assert client.put("/api/admin/plan", json={"plan": "basico"}, headers=client.admin_headers).status_code == 409


def test_limite_de_profesionales_del_plan_basico(client):
    signup = client.post(
        "/api/signup",
        json={"business_name": "Nuevo Negocio", "email": "nuevo@x.com", "password": "clave1234", "plan": "basico"},
    ).json()
    headers = {"X-Session-Token": signup["session_token"]}
    assert client.post("/api/admin/professionals", json={"name": "Primera"}, headers=headers).status_code == 200
    resp = client.post("/api/admin/professionals", json={"name": "Segunda"}, headers=headers)
    assert resp.status_code == 409
    assert "plan" in resp.json()["detail"].lower()


# --- Configuracion: servicios y profesionales ----------------------------------------------------


def test_crear_y_editar_servicio(client):
    creado = client.post(
        "/api/admin/services", json={"name": "Manicura", "duration_min": 30}, headers=client.admin_headers
    ).json()
    assert creado["active"] is True
    nombres = {s["name"] for s in client.get("/api/admin/services", headers=client.admin_headers).json()["services"]}
    assert "Manicura" in nombres

    editado = client.put(
        f"/api/admin/services/{creado['id']}",
        json={"name": "Manicura", "duration_min": 45, "active": False},
        headers=client.admin_headers,
    ).json()
    assert editado["duration_min"] == 45 and editado["active"] is False
    assert client.put(
        "/api/admin/services/999", json={"name": "XX", "duration_min": 10}, headers=client.admin_headers
    ).status_code == 404


def test_servicio_desactivado_no_se_ofrece_en_el_chat(client):
    client.put(
        "/api/admin/services/1",
        json={"name": "Corte de pelo", "duration_min": 45, "active": False},
        headers=client.admin_headers,
    )
    nombres = {s["name"] for s in client.get(f"/api/b/{client.slug}/business").json()["services"]}
    assert "Corte de pelo" not in nombres


def test_crear_y_editar_profesional(client):
    creado = client.post("/api/admin/professionals", json={"name": "Sofía"}, headers=client.admin_headers).json()
    assert creado["active"] is True
    editado = client.put(
        f"/api/admin/professionals/{creado['id']}", json={"name": "Sofía", "active": False}, headers=client.admin_headers
    ).json()
    assert editado["active"] is False
    assert client.put(
        "/api/admin/professionals/999", json={"name": "XX"}, headers=client.admin_headers
    ).status_code == 404


# --- Configuracion: horarios ----------------------------------------------------------------------


def test_configurar_horarios_reemplaza_la_franja_del_dia(client):
    resp = client.put(
        "/api/admin/working-hours",
        json={"professional_id": 1, "weekday": 0, "ranges": [{"start": "10:00", "end": "12:00"}]},
        headers=client.admin_headers,
    )
    assert resp.status_code == 200
    data = client.get("/api/admin/working-hours", headers=client.admin_headers).json()
    lunes_laura = [h for h in data["hours"] if h["professional_id"] == 1 and h["weekday"] == 0]
    assert lunes_laura == [{"professional_id": 1, "weekday": 0, "start": "10:00", "end": "12:00"}]


def test_horarios_validan_formato_y_superposicion(client):
    malformado = client.put(
        "/api/admin/working-hours",
        json={"professional_id": 1, "weekday": 0, "ranges": [{"start": "10h", "end": "12:00"}]},
        headers=client.admin_headers,
    )
    assert malformado.status_code == 422
    invertido = client.put(
        "/api/admin/working-hours",
        json={"professional_id": 1, "weekday": 0, "ranges": [{"start": "12:00", "end": "10:00"}]},
        headers=client.admin_headers,
    )
    assert invertido.status_code == 422
    superpuesto = client.put(
        "/api/admin/working-hours",
        json={
            "professional_id": 1,
            "weekday": 0,
            "ranges": [{"start": "09:00", "end": "13:00"}, {"start": "12:00", "end": "15:00"}],
        },
        headers=client.admin_headers,
    )
    assert superpuesto.status_code == 422
    assert client.put(
        "/api/admin/working-hours",
        json={"professional_id": 999, "weekday": 0, "ranges": []},
        headers=client.admin_headers,
    ).status_code == 404


def test_vaciar_los_horarios_deja_el_dia_sin_turnos(client):
    client.put(
        "/api/admin/working-hours",
        json={"professional_id": 1, "weekday": 0, "ranges": []},
        headers=client.admin_headers,
    )
    from app import db, scheduling

    conn = db.connect()
    assert scheduling.free_slots(conn, 1, 1, date(2026, 9, 21)) == []
