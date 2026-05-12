from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any

from doghouse.common.service_config import ServiceConfig
from doghouse.host_executor.policy import ExecutorPolicy, load_executor_policy
from doghouse.service_watchdog.state import utc_now_iso


@dataclass
class ExecutorResult:
    action: str
    service_id: str
    unit: str | None
    allowed: bool
    executed: bool
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    reason: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "service_id": self.service_id,
            "unit": self.unit,
            "allowed": self.allowed,
            "executed": self.executed,
            "returncode": self.returncode,
            "stdout": self.stdout[-4000:],
            "stderr": self.stderr[-4000:],
            "reason": self.reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _unit_for(service: ServiceConfig, policy: ExecutorPolicy) -> str | None:
    if service.service_id in policy.allowed_services:
        return policy.allowed_services[service.service_id]
    return service.runtime.unit


def render_argv(template: list[str], unit: str) -> list[str]:
    return [item.replace("{unit}", unit) for item in template]


def execute_host_action(
    action: str,
    service: ServiceConfig,
    policy: ExecutorPolicy | None = None,
    policy_path: str = "/opt/doghouse/config/executor-policy.yaml",
    dry_run: bool = False,
) -> ExecutorResult:
    policy = policy or load_executor_policy(policy_path)
    unit = _unit_for(service, policy)
    base = ExecutorResult(action=action, service_id=service.service_id, unit=unit, allowed=False, executed=False)
    if not policy.enabled:
        base.reason = "host executor disabled by policy"
        return base
    if action not in policy.allowed_actions:
        base.reason = "action not whitelisted"
        return base
    if not unit:
        base.reason = "service has no systemd unit"
        return base
    if policy.allowed_services and service.service_id not in policy.allowed_services:
        base.reason = "service not whitelisted"
        return base
    if action == "systemctl_restart" and policy.restart_requires_service_policy:
        if service.policy.report_only or not service.policy.restart_enabled:
            base.reason = "restart blocked by service policy"
            return base
    action_policy = policy.allowed_actions[action]
    argv = render_argv(action_policy.argv, unit)
    base.allowed = True
    if dry_run:
        base.reason = "dry run"
        return base
    base.started_at = utc_now_iso()
    try:
        completed = subprocess.run(argv, check=False, text=True, capture_output=True, timeout=action_policy.timeout_sec)
        base.returncode = completed.returncode
        base.stdout = completed.stdout
        base.stderr = completed.stderr
        base.executed = True
        base.reason = "ok" if completed.returncode == 0 else "command returned non-zero"
    except subprocess.TimeoutExpired as exc:
        base.returncode = None
        base.stdout = exc.stdout or ""
        base.stderr = exc.stderr or ""
        base.reason = f"timeout after {action_policy.timeout_sec}s"
    except OSError as exc:
        base.reason = f"{type(exc).__name__}: {exc}"
    finally:
        base.finished_at = utc_now_iso()
    return base
