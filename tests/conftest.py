import warnings
from datetime import datetime

import pytest

from app import auth, config, main

AHORA = datetime(2026, 9, 21, 10, 0)  # lunes
CLAVE = "clave-de-prueba"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "ADMIN_TOKEN", CLAVE)
    auth.reset_failures()
    main.app.dependency_overrides[main.get_now] = lambda: AHORA
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient

        with TestClient(main.app) as c:
            yield c
    main.app.dependency_overrides.clear()
