from __future__ import annotations

from fastapi.testclient import TestClient

from doghouse.api.app import create_app


def test_health_reports_api_process_liveness_only(monkeypatch):
    def fail_if_downstream_config_is_loaded():
        raise AssertionError("/health must not load config or check downstream services")

    monkeypatch.setattr("doghouse.api.app.load_config_from_env", fail_if_downstream_config_is_loaded)

    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
