from __future__ import annotations

import time
from pathlib import Path

import httpx

from doghouse.common.config import DoghouseConfig, load_config_from_env
from doghouse.common.service_config import ServiceConfig
from doghouse.devtask_watchdog.checker import check_devtasks
from doghouse.host_executor.executor import execute_host_action
from doghouse.service_watchdog.diagnostics import collect_diagnostics
from doghouse.service_watchdog.incidents import maybe_write_incident
from doghouse.service_watchdog.state import (
    EndpointCheckResult,
    ServiceCheckResult,
    read_previous_state,
    state_file,
    utc_now_iso,
    write_state_atomic,
)

RESTART_GRADE_ENDPOINTS = ("live",)
READINESS_ENDPOINTS = ("ready", "health")


def check_endpoint(name: str, url: str, timeout_sec: int) -> EndpointCheckResult:
    checked_at = utc_now_iso()
    started = time.perf_counter()
    try:
        response = httpx.get(url, timeout=timeout_sec)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return EndpointCheckResult(
            name=name,
            url=url,
            ok=200 <= response.status_code < 400,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            checked_at=checked_at,
        )
    except Exception as exc:  # report-only checker must not crash on network failures
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return EndpointCheckResult(
            name=name,
            url=url,
            ok=False,
            elapsed_ms=elapsed_ms,
            error=f"{type(exc).__name__}: {exc}",
            checked_at=checked_at,
        )


def classify(service: ServiceConfig, endpoints: dict[str, EndpointCheckResult], previous: dict) -> tuple[str, str, int]:
    live = endpoints.get("live")
    previous_count = int(previous.get("consecutive_liveness_failures", 0) or 0)

    if live is not None and live.ok:
        liveness_failures = 0
    elif live is not None:
        liveness_failures = previous_count + 1
    else:
        # Legacy/partial configs without /live are never restart-grade in Phase 2.
        liveness_failures = 0

    threshold = service.policy.failure_threshold
    readiness_results = [endpoints[name] for name in READINESS_ENDPOINTS if name in endpoints]
    failing_readiness = [item.name for item in readiness_results if not item.ok]

    if live is not None and not live.ok:
        if liveness_failures >= threshold:
            return (
                "liveness_failed_threshold_met",
                f"live endpoint failed {liveness_failures}/{threshold} consecutive checks; restart policy evaluation required",
                liveness_failures,
            )
        return (
            "liveness_failed_below_threshold",
            f"live endpoint failed {liveness_failures}/{threshold} consecutive checks; restart deferred by threshold",
            liveness_failures,
        )

    if failing_readiness:
        return (
            "degraded",
            f"liveness ok but readiness/health failed: {', '.join(failing_readiness)}",
            liveness_failures,
        )

    if endpoints and all(result.ok for result in endpoints.values()):
        return "healthy", "all configured HTTP endpoints returned success", liveness_failures

    if not endpoints:
        return "not_configured", "no HTTP endpoints configured", liveness_failures

    non_restart_failures = [name for name, result in endpoints.items() if not result.ok]
    if non_restart_failures:
        return (
            "degraded",
            f"non-restart-grade endpoint failures: {', '.join(non_restart_failures)}",
            liveness_failures,
        )

    return "unknown", "no classification rule matched", liveness_failures


def check_service(service: ServiceConfig, config: DoghouseConfig | None = None, persist: bool = True) -> ServiceCheckResult:
    config = config or load_config_from_env()
    path = state_file(config.paths.state_dir, service.service_id)
    previous = read_previous_state(path)

    endpoint_results = {
        name: check_endpoint(name, url, service.policy.timeout_sec)
        for name, url in service.endpoints.items()
        if name in {"live", "ready", "health"}
    }
    classification, reason, failures = classify(service, endpoint_results, previous)
    diagnostics = None
    incident = None
    action = None
    if classification not in {"healthy", "not_configured"}:
        diagnostics = collect_diagnostics(service)
    result = ServiceCheckResult(
        service_id=service.service_id,
        display_name=service.display_name,
        checked_at=utc_now_iso(),
        classification=classification,
        reason=reason,
        consecutive_liveness_failures=failures,
        failure_threshold=service.policy.failure_threshold,
        report_only=service.policy.report_only,
        restart_enabled=service.policy.restart_enabled,
        kill_enabled=service.policy.kill_enabled,
        endpoints=endpoint_results,
        previous_state_path=str(path) if path.exists() else None,
        state_path=str(path),
        diagnostics=diagnostics,
        action=action,
    )
    if persist:
        incident = maybe_write_incident(service, result, config, diagnostics)
        if incident is not None:
            result.incident = incident
        if classification == "liveness_failed_threshold_met":
            if service.policy.report_only or not service.policy.restart_enabled:
                result.action = {"action": "systemctl_restart", "executed": False, "reason": "report-only or restart disabled"}
            elif service.policy.active_task_guard:
                devtasks = check_devtasks(config, active_work_url=service.endpoints.get("active_work") or service.endpoints.get("watchdog_active_work"), persist=True)
                source_failures = [source for source in devtasks.get("active_work_sources", []) if source.get("ok") is False and source.get("url")]
                active = [task for task in devtasks.get("tasks", []) if task.get("classification") in {"active", "idle", "stuck", "orphaned", "unknown"}]
                if active:
                    result.action = {"action": "systemctl_restart", "executed": False, "reason": "active task guard deferred restart", "active_task_count": len(active)}
                elif source_failures and service.policy.active_task_query_failure_policy == "defer":
                    result.action = {"action": "systemctl_restart", "executed": False, "reason": "active task query failed; defer policy active", "source_failures": source_failures}
            if result.action is None:
                result.action = execute_host_action("systemctl_restart", service, policy_path=config.host_executor.policy_path).as_dict()
        write_state_atomic(path, result.model_dump(mode="json"))
    return result
