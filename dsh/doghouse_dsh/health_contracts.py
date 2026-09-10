"""Deterministic health contract engine.

This module is intentionally pure: callers provide already-collected check
observations and the engine normalizes them without invoking agents, shell
commands, HTTP clients, or live runtime actions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class HealthState(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


class CheckType(str, Enum):
    LIVE = "live"
    READY = "ready"
    HEALTH = "health"
    VERSION = "version"
    BUILD_INFO = "build-info"
    ACTIVE_WORK = "active-work"


@dataclass(frozen=True)
class HealthContract:
    service_name: str
    checks: tuple[str | CheckType, ...]
    timeout_seconds: int = 10
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class HealthResult:
    service_name: str
    state: HealthState
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckObservation:
    status_code: int | None
    body: Any
    error: str | None = None


@dataclass(frozen=True)
class NormalizedCheckStatus:
    name: str
    state: HealthState
    classification: str
    safe_to_restart: bool
    active_work: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedHealthStatus:
    service_name: str
    state: HealthState
    classification: str
    safe_to_restart: bool
    active_work: bool
    version: str | None = None
    build: str | None = None
    dependencies: Mapping[str, str] = field(default_factory=dict)
    recommended_incidents: tuple[str, ...] = ()
    checks: tuple[NormalizedCheckStatus, ...] = ()


def evaluate_health_contract(
    contract: HealthContract,
    observations: Mapping[str | CheckType, CheckObservation],
) -> NormalizedHealthStatus:
    """Normalize configured check observations into one deterministic status.

    Missing observations, transport errors, non-2xx statuses, and non-object
    response bodies are classified from the configured check order so repeated
    evaluations of the same inputs always produce the same top-level result.
    """
    if not contract.checks:
        return NormalizedHealthStatus(contract.service_name, HealthState.UNKNOWN,
                                      'no-checks-configured', False, False)
    normalized_observations = {
        _check_name(name): observation for name, observation in observations.items()
    }
    check_statuses = tuple(
        _evaluate_check(_check_name(check), normalized_observations.get(_check_name(check)))
        for check in contract.checks
    )

    active_work = any(check.active_work for check in check_statuses)
    dependencies = _first_mapping_detail(check_statuses, "dependencies")
    version = _first_string_detail(check_statuses, "version")
    build = _first_string_detail(check_statuses, "build")

    failed = tuple(check for check in check_statuses if check.state is HealthState.FAILED)
    degraded = tuple(check for check in check_statuses if check.state is HealthState.DEGRADED)

    if failed:
        state = HealthState.FAILED
        classification = failed[0].classification
    elif degraded:
        state = HealthState.DEGRADED
        classification = degraded[0].classification
    else:
        state = HealthState.HEALTHY
        classification = "healthy"

    safe_to_restart = state is not HealthState.FAILED and not active_work
    incidents = tuple(
        f"{contract.service_name}:{check.classification}"
        for check in failed
    )

    return NormalizedHealthStatus(
        service_name=contract.service_name,
        state=state,
        classification=classification,
        safe_to_restart=safe_to_restart,
        active_work=active_work,
        version=version,
        build=build,
        dependencies=dependencies,
        recommended_incidents=incidents,
        checks=check_statuses,
    )


def _evaluate_check(name: str, observation: CheckObservation | None) -> NormalizedCheckStatus:
    if observation is None:
        return _failed(name, f"missing-response:{name}")
    if observation.error:
        return _failed(name, f"check-error:{name}", {"error": observation.error})
    if observation.status_code is None or not 200 <= observation.status_code <= 299:
        return _failed(name, f"http-unhealthy:{name}", {"status_code": observation.status_code})
    if not isinstance(observation.body, dict):
        return _failed(name, f"invalid-response:{name}")

    body = observation.body
    if name == CheckType.LIVE.value:
        return _boolean_gate(name, body, "ok")
    if name == CheckType.READY.value:
        return _boolean_gate(name, body, "ready")
    if name == CheckType.HEALTH.value:
        return _health_check(name, body)
    if name == CheckType.VERSION.value:
        version = body.get("version")
        if not isinstance(version, str) or not version:
            return _failed(name, f"invalid-response:{name}")
        return _healthy(name, {"version": version})
    if name == CheckType.BUILD_INFO.value:
        build = body.get("build") or body.get("build_id") or body.get("version")
        if not isinstance(build, str) or not build:
            return _failed(name, f"invalid-response:{name}")
        details = {"build": build}
        if isinstance(body.get("git_sha"), str):
            details["git_sha"] = body["git_sha"]
        return _healthy(name, details)
    if name == CheckType.ACTIVE_WORK.value:
        return _active_work_check(name, body)

    return _custom_check(name, body)


def _boolean_gate(name: str, body: Mapping[str, Any], key: str) -> NormalizedCheckStatus:
    value = body.get(key)
    if value is True:
        return _healthy(name)
    if value is False:
        return _failed(name, f"{name}-false")
    return _failed(name, f"invalid-response:{name}")


def _health_check(name: str, body: Mapping[str, Any]) -> NormalizedCheckStatus:
    status = body.get("status", body.get("state"))
    dependencies = body.get("dependencies", {})
    if dependencies is None:
        dependencies = {}
    if not isinstance(dependencies, dict):
        return _failed(name, f"invalid-response:{name}")
    normalized_dependencies = {str(k): str(v) for k, v in sorted(dependencies.items())}
    details = {"dependencies": normalized_dependencies}
    if status in ("ok", "healthy", True):
        return _healthy(name, details)
    if status in ("degraded", "warning"):
        return NormalizedCheckStatus(
            name=name,
            state=HealthState.DEGRADED,
            classification="health-degraded",
            safe_to_restart=True,
            details=details,
        )
    if status in ("failed", "fail", "error", False):
        return _failed(name, "health-failed", details)
    return _failed(name, f"invalid-response:{name}", details)


def _active_work_check(name: str, body: Mapping[str, Any]) -> NormalizedCheckStatus:
    raw = body.get("active_work", body.get("active", body.get("count")))
    if isinstance(raw, bool):
        active = raw
    elif isinstance(raw, int):
        active = raw > 0
    elif isinstance(raw, list):
        active = len(raw) > 0
    else:
        return _failed(name, f"invalid-response:{name}")

    details: dict[str, Any] = {"active_work": raw}
    if isinstance(body.get("items"), list):
        details["items"] = tuple(str(item) for item in body["items"])

    if active:
        return NormalizedCheckStatus(
            name=name,
            state=HealthState.DEGRADED,
            classification="active-work-present",
            safe_to_restart=False,
            active_work=True,
            details=details,
        )
    return _healthy(name, details)


def _custom_check(name: str, body: Mapping[str, Any]) -> NormalizedCheckStatus:
    status = body.get("status", body.get("state"))
    if status in ("ok", "healthy", "ready", True):
        return _healthy(name, dict(body))
    if status in ("degraded", "warning"):
        return NormalizedCheckStatus(
            name=name,
            state=HealthState.DEGRADED,
            classification=f"{name}-degraded",
            safe_to_restart=True,
            details=dict(body),
        )
    if status in ("failed", "fail", "error", False):
        return _failed(name, f"{name}-failed", dict(body))
    return _failed(name, f"invalid-response:{name}", dict(body))


def _healthy(name: str, details: Mapping[str, Any] | None = None) -> NormalizedCheckStatus:
    return NormalizedCheckStatus(
        name=name,
        state=HealthState.HEALTHY,
        classification="healthy",
        safe_to_restart=True,
        details={} if details is None else details,
    )


def _failed(
    name: str,
    classification: str,
    details: Mapping[str, Any] | None = None,
) -> NormalizedCheckStatus:
    return NormalizedCheckStatus(
        name=name,
        state=HealthState.FAILED,
        classification=classification,
        safe_to_restart=False,
        details={} if details is None else details,
    )


def _check_name(check: str | CheckType) -> str:
    if isinstance(check, CheckType):
        return check.value
    return str(check)


def _first_string_detail(checks: tuple[NormalizedCheckStatus, ...], key: str) -> str | None:
    for check in checks:
        value = check.details.get(key)
        if isinstance(value, str):
            return value
    return None


def _first_mapping_detail(
    checks: tuple[NormalizedCheckStatus, ...],
    key: str,
) -> Mapping[str, str]:
    for check in checks:
        value = check.details.get(key)
        if isinstance(value, dict):
            return value
    return {}
