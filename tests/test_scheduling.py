from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

import pytest

from app import db, scheduling

LUNES = date(2026, 9, 21)  # weekday() == 0


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    c.execute(
        "INSERT INTO businesses (id, slug, name, email, password_hash, created_at) "
        "VALUES (1, 'demo', 'Demo', 'demo@x.com', 'x', '2026-01-01')"
    )
    c.execute("INSERT INTO services (id, business_id, name, duration_min) VALUES (1, 1, 'Corte', 60)")
    c.execute("INSERT INTO professionals (id, business_id, name) VALUES (1, 1, 'Laura')")
    c.execute("INSERT INTO working_hours (business_id, professional_id, weekday, start, end) VALUES (1, 1, 0, '09:00', '12:00')")
    c.execute("INSERT INTO customers (id, business_id, name) VALUES (1, 1, 'Ana')")
    c.commit()
    return c


def test_free_slots_respeta_horario_y_duracion(conn):
    slots = scheduling.free_slots(conn, 1, 1, 1, LUNES)
    assert slots[0] == datetime(2026, 9, 21, 9, 0)
    assert slots[-1] == datetime(2026, 9, 21, 11, 0)  # el ultimo que termina a las 12


def test_dia_sin_atencion_no_tiene_slots(conn):
    assert scheduling.free_slots(conn, 1, 1, 1, date(2026, 9, 22)) == []


def test_book_bloquea_horarios_superpuestos(conn):
    scheduling.book(conn, 1, 1, 1, 1, datetime(2026, 9, 21, 10, 0))
    slots = scheduling.free_slots(conn, 1, 1, 1, LUNES)
    assert datetime(2026, 9, 21, 10, 0) not in slots
    assert datetime(2026, 9, 21, 10, 30) not in slots
    assert datetime(2026, 9, 21, 9, 15) not in slots  # terminaria a las 10:15
    assert datetime(2026, 9, 21, 9, 0) in slots
    assert datetime(2026, 9, 21, 11, 0) in slots


def test_book_falla_si_el_horario_esta_ocupado(conn):
    scheduling.book(conn, 1, 1, 1, 1, datetime(2026, 9, 21, 10, 0))
    with pytest.raises(scheduling.SlotUnavailable):
        scheduling.book(conn, 1, 1, 1, 1, datetime(2026, 9, 21, 10, 0))


def test_book_falla_fuera_de_horario(conn):
    with pytest.raises(scheduling.SlotUnavailable):
        scheduling.book(conn, 1, 1, 1, 1, datetime(2026, 9, 21, 20, 0))


def test_cancelar_libera_el_horario(conn):
    turno = scheduling.book(conn, 1, 1, 1, 1, datetime(2026, 9, 21, 10, 0))
    scheduling.cancel(conn, 1, turno)
    assert datetime(2026, 9, 21, 10, 0) in scheduling.free_slots(conn, 1, 1, 1, LUNES)


def test_no_ofrece_horarios_pasados(conn):
    ahora = datetime(2026, 9, 21, 10, 0)
    slots = scheduling.free_slots(conn, 1, 1, 1, LUNES, now=ahora)
    assert all(s > ahora for s in slots)


def test_dos_reservas_concurrentes_no_ocupan_el_mismo_horario(tmp_path):
    path = str(tmp_path / "concurrent.db")
    setup = db.connect(path)
    db.init_db(setup)
    setup.execute(
        """INSERT INTO businesses (id, slug, name, email, password_hash, created_at)
           VALUES (1, 'demo', 'Demo', 'demo@x.com', 'x', '2026-01-01')"""
    )
    setup.execute("INSERT INTO services (id, business_id, name, duration_min) VALUES (1, 1, 'Corte', 60)")
    setup.execute("INSERT INTO professionals (id, business_id, name) VALUES (1, 1, 'Laura')")
    setup.execute(
        "INSERT INTO working_hours (business_id, professional_id, weekday, start, end) VALUES (1, 1, 0, '09:00', '12:00')"
    )
    setup.executemany(
        "INSERT INTO customers (id, business_id, name) VALUES (?, 1, ?)", [(1, "Ana"), (2, "Beto")]
    )
    setup.commit()
    setup.close()
    barrier = threading.Barrier(2)

    def reserve(customer_id):
        worker = db.connect(path)
        barrier.wait()
        try:
            scheduling.book(worker, 1, customer_id, 1, 1, datetime(2026, 9, 21, 10, 0))
            return True
        except scheduling.SlotUnavailable:
            return False
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, (1, 2)))
    assert sorted(results) == [False, True]
    check = db.connect(path)
    assert check.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1


def test_la_base_rechaza_referencias_entre_negocios(conn):
    conn.execute(
        """INSERT INTO businesses (id, slug, name, email, password_hash, created_at)
           VALUES (2, 'otro', 'Otro', 'otro@x.com', 'x', '2026-01-01')"""
    )
    conn.execute("INSERT INTO professionals (id, business_id, name) VALUES (2, 2, 'Ajeno')")
    with pytest.raises(sqlite3.IntegrityError, match="tenant mismatch"):
        conn.execute(
            """INSERT INTO appointments
               (business_id, customer_id, professional_id, service_id, start, end)
               VALUES (1, 1, 2, 1, '2026-09-21T10:00:00', '2026-09-21T11:00:00')"""
        )
