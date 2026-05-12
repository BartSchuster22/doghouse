from pathlib import Path

from doghouse.common.config import DoghouseConfig, PathsConfig
from doghouse.common.service_config import ServiceConfig
from doghouse.service_watchdog.checker import classify
from doghouse.service_watchdog.state import EndpointCheckResult
from doghouse.soak.report import _parse_since


def endpoint(name: str, ok: bool) -> EndpointCheckResult:
    return EndpointCheckResult(name=name, url=f"http://local/{name}", ok=ok, checked_at="2026-01-01T00:00:00Z")


def test_liveness_threshold_classification():
    service = ServiceConfig(service_id="svc", display_name="Svc")
    classification, reason, failures = classify(service, {"live": endpoint("live", False)}, {"consecutive_liveness_failures": 2})
    assert classification == "liveness_failed_threshold_met"
    assert failures == 3
    assert "3/3" in reason


def test_readiness_failure_is_degraded_not_restart_grade():
    service = ServiceConfig(service_id="svc", display_name="Svc")
    classification, reason, failures = classify(service, {"live": endpoint("live", True), "ready": endpoint("ready", False)}, {})
    assert classification == "degraded"
    assert failures == 0
    assert "ready" in reason


def test_soak_since_accepts_minutes():
    systemd, since_dt = _parse_since("15m")
    assert systemd == "15 minutes ago"
    assert since_dt.tzinfo is not None


def test_endpoint_modes_load_from_service_yaml():
    service = ServiceConfig.model_validate({
        "service_id": "svc",
        "display_name": "Svc",
        "endpoints": {"live": "http://127.0.0.1/live"},
        "endpoint_modes": {"live": "native"},
    })
    assert service.endpoint_modes["live"] == "native"
