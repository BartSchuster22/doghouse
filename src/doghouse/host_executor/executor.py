from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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
    audit_path: str | None = None
    destructive: bool = False
    request_reason: str | None = None
    confirmation_required: str | None = None
    audit_hash: str | None = None
    previous_audit_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "service_id": self.service_id,
            "unit": self.unit,
            "allowed": self.allowed,
            "executed": self.executed,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "reason": self.reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "audit_path": self.audit_path,
            "destructive": self.destructive,
            "request_reason": self.request_reason,
            "confirmation_required": self.confirmation_required,
            "audit_hash": self.audit_hash,
            "previous_audit_hash": self.previous_audit_hash,
        }


def _unit_for(service: ServiceConfig, policy: ExecutorPolicy) -> str | None:
    if service.service_id in policy.allowed_services:
        return policy.allowed_services[service.service_id]
    return service.runtime.unit


def render_argv(template: list[str], unit: str) -> list[str]:
    return [item.replace("{unit}", unit) for item in template]


def _safe_env() -> dict[str, str]:
    return {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def _last_audit_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        for line in reversed(path.read_text(encoding="utf-8").splitlines()[-200:]):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("audit_hash"):
                return str(rec["audit_hash"])
    except OSError:
        return None
    return None


def _append_audit(policy: ExecutorPolicy, result: ExecutorResult, argv: list[str] | None = None) -> None:
    path = Path(policy.audit_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = _last_audit_hash(path) if policy.audit_include_hash_chain else None
    result.previous_audit_hash = previous
    record = result.as_dict() | {"recorded_at": utc_now_iso(), "argv": argv or []}
    if policy.audit_include_hash_chain:
        payload = json.dumps(record | {"audit_hash": None}, sort_keys=True, separators=(",", ":"))
        result.audit_hash = hashlib.sha256(((previous or "") + payload).encode("utf-8")).hexdigest()
        record = result.as_dict() | {"recorded_at": record["recorded_at"], "argv": argv or []}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    result.audit_path = str(path)


def _last_restart_age_sec(policy: ExecutorPolicy, service_id: str) -> int | None:
    path = Path(policy.audit_log_path)
    if not path.exists():
        return None
    now = datetime.now(timezone.utc)
    last: datetime | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-500:]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("service_id") == service_id and rec.get("action") == "systemctl_restart" and rec.get("executed") is True:
            ts = rec.get("finished_at") or rec.get("started_at") or rec.get("recorded_at")
            try:
                last = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                break
            except Exception:
                continue
    if not last:
        return None
    return int((now - last).total_seconds())


def destructive_confirmation_token(service_id: str, action: str) -> str:
    return f"EXECUTE:{service_id}:{action}"


def validate_executor_request(action: str, service: ServiceConfig, policy: ExecutorPolicy, dry_run: bool, reason: str | None = None, confirmation_token: str | None = None) -> tuple[bool, str | None, str | None, list[str] | None, bool]:
    unit = _unit_for(service, policy)
    if not policy.enabled:
        return False, "host executor disabled by policy", unit, None, False
    if action not in policy.allowed_actions:
        return False, "action not whitelisted", unit, None, False
    if not unit:
        return False, "service has no systemd unit", unit, None, False
    if policy.allowed_services and service.service_id not in policy.allowed_services:
        return False, "service not whitelisted", unit, None, False
    if not re.match(policy.unit_name_regex, unit):
        return False, "unit name rejected by regex policy", unit, None, False
    action_policy = policy.allowed_actions[action]
    argv = render_argv(action_policy.argv, unit)
    if not argv:
        return False, "empty argv rejected", unit, None, action_policy.destructive
    if policy.require_absolute_argv0 and not argv[0].startswith("/"):
        return False, "argv[0] must be an absolute path", unit, argv, action_policy.destructive
    if policy.allowed_binaries and argv[0] not in policy.allowed_binaries:
        return False, "argv[0] not in allowed_binaries", unit, argv, action_policy.destructive
    if any(any(ch in item for ch in [";", "&&", "||", "`", "$(", "\n"]) for item in argv):
        return False, "shell metacharacter rejected", unit, argv, action_policy.destructive
    if action_policy.requires_execute_flag and dry_run:
        return True, "dry run", unit, argv, action_policy.destructive
    if action_policy.destructive and not dry_run:
        if policy.require_reason_for_destructive and len((reason or "").strip()) < policy.min_destructive_reason_chars:
            return False, "destructive action requires operator reason", unit, argv, action_policy.destructive
        required = destructive_confirmation_token(service.service_id, action)
        if policy.require_confirmation_token_for_destructive and confirmation_token != required:
            return False, f"destructive action requires confirmation token: {required}", unit, argv, action_policy.destructive
    if action == "systemctl_restart" and policy.restart_requires_service_policy:
        if service.policy.report_only or not service.policy.restart_enabled:
            return False, "restart blocked by service policy", unit, argv, action_policy.destructive
        age = _last_restart_age_sec(policy, service.service_id)
        if age is not None and age < policy.restart_cooldown_sec:
            return False, f"restart cooldown active: last restart {age}s ago", unit, argv, action_policy.destructive
    return True, None, unit, argv, action_policy.destructive


def execute_host_action(
    action: str,
    service: ServiceConfig,
    policy: ExecutorPolicy | None = None,
    policy_path: str = "/opt/doghouse/config/executor-policy.yaml",
    dry_run: bool = False,
    reason: str | None = None,
    confirmation_token: str | None = None,
) -> ExecutorResult:
    policy = policy or load_executor_policy(policy_path)
    allowed, validation_reason, unit, argv, destructive = validate_executor_request(action, service, policy, dry_run, reason=reason, confirmation_token=confirmation_token)
    base = ExecutorResult(action=action, service_id=service.service_id, unit=unit, allowed=allowed, executed=False, reason=validation_reason, destructive=destructive, request_reason=reason)
    if destructive:
        base.confirmation_required = destructive_confirmation_token(service.service_id, action)
    if not allowed or dry_run:
        _append_audit(policy, base, argv)
        return base
    base.started_at = utc_now_iso()
    try:
        completed = subprocess.run(argv or [], check=False, text=True, capture_output=True, timeout=policy.allowed_actions[action].timeout_sec, env=_safe_env(), cwd="/", shell=False)
        base.returncode = completed.returncode
        base.stdout = (completed.stdout or "")[-policy.max_output_chars:]
        base.stderr = (completed.stderr or "")[-policy.max_output_chars:]
        base.executed = True
        base.reason = "ok" if completed.returncode == 0 else "command returned non-zero"
    except subprocess.TimeoutExpired as exc:
        base.returncode = None
        base.stdout = (exc.stdout or "")[-policy.max_output_chars:] if isinstance(exc.stdout, str) else ""
        base.stderr = (exc.stderr or "")[-policy.max_output_chars:] if isinstance(exc.stderr, str) else ""
        base.reason = f"timeout after {policy.allowed_actions[action].timeout_sec}s"
    except OSError as exc:
        base.reason = f"{type(exc).__name__}: {exc}"
    finally:
        base.finished_at = utc_now_iso()
        _append_audit(policy, base, argv)
    return base
