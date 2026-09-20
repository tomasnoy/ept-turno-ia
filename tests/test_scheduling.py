from datetime import date, datetime

import pytest

from app import db, scheduling

LUNES = date(2026, 9, 21)  # weekday() == 0


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    c.execute("INSERT INTO services (id, name, duration_min) VALUES (1, 'Corte', 60)")
    c.execute("INSERT INTO professionals (id, name) VALUES (1, 'Laura')")
    c.execute("INSERT INTO working_hours VALUES (1, 0, '09:00', '12:00')")
    c.execute("INSERT INTO customers (id, name) VALUES (1, 'Ana')")
    c.commit()
    return c


def test_free_slots_respeta_horario_y_duracion(conn):
    slots = scheduling.free_slots(conn, 1, 1, LUNES)
    assert slots[0] == datetime(2026, 9, 21, 9, 0)
    assert slots[-1] == datetime(2026, 9, 21, 11, 0)  # el ultimo que termina a las 12


def test_dia_sin_atencion_no_tiene_slots(conn):
    assert scheduling.free_slots(conn, 1, 1, date(2026, 9, 22)) == []


def test_book_bloquea_horarios_superpuestos(conn):
    scheduling.book(conn, 1, 1, 1, datetime(2026, 9, 21, 10, 0))
    slots = scheduling.free_slots(conn, 1, 1, LUNES)
    assert datetime(2026, 9, 21, 10, 0) not in slots
    assert datetime(2026, 9, 21, 10, 30) not in slots
    assert datetime(2026, 9, 21, 9, 15) not in slots  # terminaria a las 10:15
    assert datetime(2026, 9, 21, 9, 0) in slots
    assert datetime(2026, 9, 21, 11, 0) in slots


def test_book_falla_si_el_horario_esta_ocupado(conn):
    scheduling.book(conn, 1, 1, 1, datetime(2026, 9, 21, 10, 0))
    with pytest.raises(scheduling.SlotUnavailable):
        scheduling.book(conn, 1, 1, 1, datetime(2026, 9, 21, 10, 0))


def test_book_falla_fuera_de_horario(conn):
    with pytest.raises(scheduling.SlotUnavailable):
        scheduling.book(conn, 1, 1, 1, datetime(2026, 9, 21, 20, 0))


def test_cancelar_libera_el_horario(conn):
    turno = scheduling.book(conn, 1, 1, 1, datetime(2026, 9, 21, 10, 0))
    scheduling.cancel(conn, turno)
    assert datetime(2026, 9, 21, 10, 0) in scheduling.free_slots(conn, 1, 1, LUNES)


def test_no_ofrece_horarios_pasados(conn):
    ahora = datetime(2026, 9, 21, 10, 0)
    slots = scheduling.free_slots(conn, 1, 1, LUNES, now=ahora)
    assert all(s > ahora for s in slots)
