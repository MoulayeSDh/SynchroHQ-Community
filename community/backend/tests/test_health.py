from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import app.main as main


def test_health_checks_database(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    test_engine = create_engine("sqlite://")
    monkeypatch.setattr(main, "engine", test_engine)
    response = TestClient(main.create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_identity_requires_bearer_token(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    test_engine = create_engine("sqlite://")
    monkeypatch.setattr(main, "engine", test_engine)
    response = TestClient(main.create_app()).get("/api/me")
    assert response.status_code == 401
