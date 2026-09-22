import warnings
from datetime import datetime

import pytest

from app import auth, config, main
from app.seed import DEMO_EMAIL, DEMO_PASSWORD

AHORA = datetime(2026, 9, 21, 10, 0)  # lunes
SLUG = "peluqueria-demo"  # negocio demo que se siembra solo al arrancar la app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    auth.reset_failures()
    main.app.dependency_overrides[main.get_now] = lambda: AHORA
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient

        with TestClient(main.app) as c:
            login = c.post("/api/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
            c.admin_headers = {"X-Session-Token": login.json()["session_token"]}
            c.slug = SLUG
            yield c
    main.app.dependency_overrides.clear()
