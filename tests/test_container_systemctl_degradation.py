from __future__ import annotations

from fastapi.testclient import TestClient

from doghouse.api.app import create_app
from doghouse.common.service_config import ServiceConfig
from doghouse.service_watchdog.state import ServiceCheckResult


def test_shadow_endpoint_reports_attention_when_systemctl_is_unavailable(monkeypatch):
    service = ServiceConfig.model_validate(
        {
            "service_id": "openclaw",
            "display_name": "OpenClaw Gateway",
            "runtime": {"type": "systemd", "unit": "openclaw.service"},
            "policy": {"report_only": True, "restart_enabled": False, "kill_enabled": False},
        }
    )
    service_check = ServiceCheckResult(
        service_id="openclaw",
        display_name="OpenClaw Gateway",
        checked_at="2026-06-12T22:00:00Z",
        classification="healthy",
        reason="all configured HTTP endpoints returned success",
        consecutive_liveness_failures=0,
        failure_threshold=3,
        report_only=True,
        restart_enabled=False,
        kill_enabled=False,
        endpoints={},
    )

    monkeypatch.setattr("doghouse.shadow.checker.load_services", lambda _root: [service])
    monkeypatch.setattr("doghouse.shadow.checker.check_service", lambda *_args, **_kwargs: service_check)

    def missing_systemctl(*_args, **_kwargs):
        raise FileNotFoundError("systemctl")

    monkeypatch.setattr("doghouse.shadow.checker.subprocess.run", missing_systemctl)

    response = TestClient(create_app()).get("/api/v1/shadow")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "attention"
    assert payload["mode"] == "shadow"
    assert payload["items"][0]["service_id"] == "openclaw"
    assert payload["items"][0]["old_timer_enabled"].startswith("error:FileNotFoundError")
    assert payload["items"][0]["old_timer_active"].startswith("error:FileNotFoundError")
    assert "systemctl unavailable" in payload["items"][0]["notes"]


def test_openclaw_readiness_marks_systemctl_unavailable_as_attention(monkeypatch):
    from doghouse.readiness.openclaw import check_openclaw_readiness
    from doghouse.common.config import DoghouseConfig, PathsConfig

    service = ServiceConfig.model_validate(
        {
            "service_id": "openclaw",
            "display_name": "OpenClaw Gateway",
            "runtime": {"type": "systemd", "unit": "openclaw.service"},
            "endpoints": {"health": "http://127.0.0.1:18789/health"},
            "policy": {"report_only": True, "restart_enabled": False, "kill_enabled": False},
        }
    )
    service_check = ServiceCheckResult(
        service_id="openclaw",
        display_name="OpenClaw Gateway",
        checked_at="2026-06-12T22:00:00Z",
        classification="healthy",
        reason="all configured HTTP endpoints returned success",
        consecutive_liveness_failures=0,
        failure_threshold=3,
        report_only=True,
        restart_enabled=False,
        kill_enabled=False,
        endpoints={},
    )

    monkeypatch.setattr("doghouse.readiness.openclaw.load_services", lambda _root: [service])
    monkeypatch.setattr("doghouse.readiness.openclaw.check_endpoint", lambda *_args, **_kwargs: type("Endpoint", (), {"model_dump": lambda self, mode=None: {"ok": True}})())
    monkeypatch.setattr("doghouse.readiness.openclaw.check_service", lambda *_args, **_kwargs: service_check)

    def missing_systemctl(*_args, **_kwargs):
        raise FileNotFoundError("/bin/systemctl")

    monkeypatch.setattr("doghouse.readiness.openclaw.subprocess.run", missing_systemctl)

    result = check_openclaw_readiness(
        DoghouseConfig(paths=PathsConfig(state_dir="/tmp/doghouse-test-state")),
        persist=False,
    )

    assert result["status"] == "attention"
    assert result["requirements"]["systemctl_available"] is False
    assert result["unit"]["status"] == "unavailable"
    assert result["old_watchdog_timer"]["status"] == "unavailable"
    assert result["doghouse_timer"]["status"] == "unavailable"
