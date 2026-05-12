from __future__ import annotations

import json
import os
import subprocess
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doghouse.common.config import DoghouseConfig, load_config_from_env
from doghouse.common.service_config import ServiceConfig, load_services
from doghouse.host_executor.policy import load_executor_policy
from doghouse.notifications.notifier import notification_status
from doghouse.service_watchdog.state import state_file, utc_now_iso


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _writable_dir(path: str | Path) -> dict[str, Any]:
    root = Path(path)
    result = {"path": str(root), "exists": root.exists(), "is_dir": root.is_dir(), "writable": False}
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".doghouse-write-probe"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
        result.update({"exists": True, "is_dir": True, "writable": True})
    except OSError as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _systemctl_show_unit(unit: str) -> dict[str, Any]:
    try:
        p = subprocess.run(["/bin/systemctl", "show", unit, "--property=LoadState,ActiveState,SubState,UnitFileState"], text=True, capture_output=True, timeout=10, check=False)
        props = {}
        for line in p.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v
        return {"unit": unit, "returncode": p.returncode, **props, "stderr": p.stderr[-1000:]}
    except Exception as exc:
        return {"unit": unit, "error": f"{type(exc).__name__}: {exc}"}


def check_scheduler_freshness(config: DoghouseConfig, services: list[ServiceConfig]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    items = []
    max_age = max(config.scheduler.service_interval_sec * 3, 180)
    for service in services:
        path = state_file(config.paths.state_dir, service.service_id)
        item = {"service_id": service.service_id, "state_path": str(path), "fresh": False, "exists": path.exists(), "max_age_sec": max_age}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                checked = _parse_iso(data.get("checked_at", ""))
                if checked:
                    age = (now - checked).total_seconds()
                    item.update({"checked_at": data.get("checked_at"), "age_sec": int(age), "fresh": age <= max_age, "classification": data.get("classification")})
                else:
                    item["reason"] = "missing/invalid checked_at"
            except (OSError, json.JSONDecodeError) as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
        else:
            item["reason"] = "state file missing"
        items.append(item)
    return {"status": "ok" if all(item["fresh"] for item in items) else "attention", "items": items}


def check_policy(services: list[ServiceConfig], config: DoghouseConfig) -> dict[str, Any]:
    violations = []
    for service in services:
        if service.policy.kill_enabled:
            violations.append({"service_id": service.service_id, "severity": "critical", "reason": "kill_enabled is true"})
        if service.policy.restart_enabled and service.policy.report_only:
            violations.append({"service_id": service.service_id, "severity": "warning", "reason": "restart_enabled true while report_only true"})
        if service.policy.failure_threshold < 2:
            violations.append({"service_id": service.service_id, "severity": "warning", "reason": "failure_threshold below 2"})
        if service.policy.restart_enabled and not service.policy.active_task_guard:
            violations.append({"service_id": service.service_id, "severity": "warning", "reason": "restart enabled without active_task_guard"})
    if config.safety.default_kill_enabled:
        violations.append({"service_id": "default", "severity": "critical", "reason": "default_kill_enabled is true"})
    if config.safety.default_restart_enabled:
        violations.append({"service_id": "default", "severity": "warning", "reason": "default_restart_enabled is true"})
    return {"status": "ok" if not violations else "attention", "violations": violations}


def check_paths(config: DoghouseConfig) -> dict[str, Any]:
    paths = {
        "state_dir": _writable_dir(config.paths.state_dir),
        "log_dir": _writable_dir(config.paths.log_dir),
        "incident_dir": _writable_dir(config.paths.incident_dir),
        "checkpoint_dir": _writable_dir(config.paths.checkpoint_dir),
    }
    return {"status": "ok" if all(item["writable"] for item in paths.values()) else "attention", "paths": paths}


def check_systemd_units(services: list[ServiceConfig]) -> dict[str, Any]:
    items = []
    for service in services:
        new_timer = f"doghouse-check@{service.service_id}.timer"
        old_timer = f"watchdog-{service.service_id}.timer"
        runtime = service.runtime.unit or f"{service.service_id}.service"
        items.append({"service_id": service.service_id, "runtime": _systemctl_show_unit(runtime), "doghouse_timer": _systemctl_show_unit(new_timer), "old_watchdog_timer": _systemctl_show_unit(old_timer)})
    ok = all(item["doghouse_timer"].get("ActiveState") == "active" and item["doghouse_timer"].get("UnitFileState") == "enabled" for item in items)
    return {"status": "ok" if ok else "attention", "items": items}


def check_old_watchdog_migration(services: list[ServiceConfig]) -> dict[str, Any]:
    items = []
    attention = False
    for service in services:
        timer_state = _systemctl_show_unit(f"watchdog-{service.service_id}.timer")
        active = timer_state.get("ActiveState") == "active"
        enabled = timer_state.get("UnitFileState") == "enabled"
        if service.policy.restart_enabled and (active or enabled):
            attention = True
        items.append({
            "service_id": service.service_id,
            "old_timer_path": f"/etc/systemd/system/watchdog-{service.service_id}.timer",
            "old_timer_file_exists": Path(f"/etc/systemd/system/watchdog-{service.service_id}.timer").exists(),
            "old_timer_active": active,
            "old_timer_enabled": enabled,
            "doghouse_restart_enabled": service.policy.restart_enabled,
            "cutover_state": "attention-old-and-new-enabled" if service.policy.restart_enabled and (active or enabled) else "ok-or-inventory",
        })
    return {"status": "attention" if attention else "ok", "items": items}


def check_executor_policy(config: DoghouseConfig, services: list[ServiceConfig]) -> dict[str, Any]:
    policy = load_executor_policy(config.host_executor.policy_path)
    issues = []
    if not policy.enabled:
        issues.append({"severity": "warning", "reason": "executor policy disabled"})
    if not policy.require_absolute_argv0:
        issues.append({"severity": "critical", "reason": "require_absolute_argv0 is false"})
    if not policy.allowed_binaries:
        issues.append({"severity": "critical", "reason": "allowed_binaries is empty"})
    if not policy.require_reason_for_destructive:
        issues.append({"severity": "critical", "reason": "destructive actions do not require reason"})
    if not policy.require_confirmation_token_for_destructive:
        issues.append({"severity": "critical", "reason": "destructive actions do not require confirmation token"})
    if policy.min_destructive_reason_chars < 8:
        issues.append({"severity": "warning", "reason": "destructive reason minimum is too short"})
    if not policy.audit_include_hash_chain:
        issues.append({"severity": "warning", "reason": "executor audit hash chain disabled"})
    for action_name, action in policy.allowed_actions.items():
        if not action.argv:
            issues.append({"severity": "critical", "action": action_name, "reason": "empty argv"})
        elif policy.require_absolute_argv0 and not action.argv[0].startswith("/"):
            issues.append({"severity": "critical", "action": action_name, "reason": "argv0 not absolute"})
        if action.destructive and not action.requires_execute_flag:
            issues.append({"severity": "critical", "action": action_name, "reason": "destructive action does not require execute flag"})
    for service in services:
        if service.policy.restart_enabled and service.service_id not in policy.allowed_services:
            issues.append({"severity": "warning", "service_id": service.service_id, "reason": "restart-enabled service not executor-whitelisted"})
    return {"status": "ok" if not issues else "attention", "issues": issues, "policy_path": config.host_executor.policy_path, "audit_log_path": policy.audit_log_path}


def check_devtask_state(config: DoghouseConfig) -> dict[str, Any]:
    path = Path(config.paths.state_dir) / "devtasks" / "last-check.json"
    hb_dir = Path(config.paths.state_dir) / "devtasks" / "heartbeats"
    result = {"state_path": str(path), "heartbeat_dir": str(hb_dir), "heartbeat_files": len(list(hb_dir.glob("*.json"))) if hb_dir.exists() else 0}
    if not path.exists():
        result.update({"status": "attention", "reason": "devtask check has not run"})
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        checked = _parse_iso(str(data.get("checked_at", "")))
        age = int((datetime.now(timezone.utc) - checked).total_seconds()) if checked else None
        max_age = max(config.scheduler.devtask_interval_sec * 6, 600)
        result.update({"status": "ok" if age is not None and age <= max_age else "attention", "checked_at": data.get("checked_at"), "age_sec": age, "max_age_sec": max_age, "task_count": data.get("task_count"), "devtask_status": data.get("status")})
    except (OSError, json.JSONDecodeError) as exc:
        result.update({"status": "attention", "error": f"{type(exc).__name__}: {exc}"})
    return result


def check_shadow_state(config: DoghouseConfig) -> dict[str, Any]:
    path = Path(config.paths.state_dir) / "shadow" / "last-shadow-report.json"
    if not path.exists():
        return {"status": "attention", "state_path": str(path), "reason": "shadow state missing"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        checked = _parse_iso(str(data.get("checked_at", "")))
        age = int((datetime.now(timezone.utc) - checked).total_seconds()) if checked else None
        max_age = max(config.scheduler.service_interval_sec * 6, 600)
        return {"status": "ok" if data.get("status") == "ok" and age is not None and age <= max_age else "attention", "state_path": str(path), "checked_at": data.get("checked_at"), "age_sec": age, "max_age_sec": max_age, "shadow_status": data.get("status")}
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "attention", "state_path": str(path), "error": f"{type(exc).__name__}: {exc}"}



def check_executor_audit_chain(config: DoghouseConfig) -> dict[str, Any]:
    policy = load_executor_policy(config.host_executor.policy_path)
    path = Path(policy.audit_log_path)
    if not path.exists():
        return {"status": "ok", "audit_log_path": str(path), "records_checked": 0, "reason": "audit log not created yet"}
    issues = []
    records = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-200:]
    except OSError as exc:
        return {"status": "attention", "audit_log_path": str(path), "error": f"{type(exc).__name__}: {exc}"}
    previous_hash = None
    hash_chain_started = False
    legacy_records = 0
    for idx, line in enumerate(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append({"line_offset": idx, "severity": "warning", "reason": f"invalid json: {exc}"})
            continue
        records.append(rec)
        if policy.audit_include_hash_chain:
            if not rec.get("audit_hash"):
                if hash_chain_started:
                    issues.append({"line_offset": idx, "severity": "warning", "reason": "missing audit_hash after hash chain started"})
                else:
                    legacy_records += 1
                continue
            hash_chain_started = True
            if previous_hash is not None and rec.get("previous_audit_hash") != previous_hash:
                issues.append({"line_offset": idx, "severity": "warning", "reason": "previous_audit_hash does not match preceding record"})
            previous_hash = rec.get("audit_hash")
    destructive_without_reason = [r for r in records if r.get("destructive") and r.get("executed") and not r.get("request_reason")]
    if destructive_without_reason:
        issues.append({"severity": "critical", "reason": "executed destructive action without recorded request_reason", "count": len(destructive_without_reason)})
    return {"status": "ok" if not issues else "attention", "audit_log_path": str(path), "records_checked": len(records), "legacy_records_without_hash": legacy_records, "issues": issues, "last_audit_hash": previous_hash}


def check_notifications(config: DoghouseConfig) -> dict[str, Any]:
    status = notification_status(config)
    issues = []
    if not status.get("enabled"):
        issues.append({"severity": "warning", "reason": "notifications disabled"})
    outbox_parent = Path(status["outbox_path"]).parent
    try:
        outbox_parent.mkdir(parents=True, exist_ok=True)
        probe = outbox_parent / ".doghouse-notification-probe"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        issues.append({"severity": "critical", "reason": f"notification outbox not writable: {type(exc).__name__}: {exc}"})
    return {"status": "ok" if not issues else "attention", **status, "issues": issues}


def summarize_audit_quality(sections: dict[str, Any]) -> dict[str, Any]:
    critical = 0
    warnings = 0
    recommendations: list[str] = []
    for name, section in sections.items():
        if not isinstance(section, dict):
            continue
        if section.get("status") not in {"ok", "inventory"}:
            warnings += 1
            recommendations.append(f"Review audit section {name}")
        for key in ("issues", "violations"):
            for issue in section.get(key, []) if isinstance(section.get(key), list) else []:
                if issue.get("severity") == "critical":
                    critical += 1
                else:
                    warnings += 1
    score = max(0.0, 10.0 - critical * 2.0 - warnings * 0.5)
    return {"score": score, "critical_count": critical, "warning_count": warnings, "recommendations": recommendations[:20], "status": "ok" if score >= 8.0 and critical == 0 else "attention"}

def run_audit(config: DoghouseConfig | None = None, services_dir: str | Path | None = None, persist: bool = True) -> dict[str, Any]:
    config = config or load_config_from_env()
    root = Path(services_dir or ("/opt/doghouse/config/services.d" if Path("/opt/doghouse/config/services.d").exists() else "config/services.d"))
    services = load_services(root)
    sections = {
        "scheduler_freshness": check_scheduler_freshness(config, services),
        "policy": check_policy(services, config),
        "paths": check_paths(config),
        "systemd_units": check_systemd_units(services),
        "old_watchdog_migration": check_old_watchdog_migration(services),
        "executor_policy": check_executor_policy(config, services),
        "executor_audit_chain": check_executor_audit_chain(config),
        "devtask_state": check_devtask_state(config),
        "shadow_state": check_shadow_state(config),
        "notifications": check_notifications(config),
    }
    quality = summarize_audit_quality(sections)
    status = "ok" if all(section.get("status") in {"ok", "inventory"} for section in sections.values()) and quality.get("status") == "ok" else "attention"
    result = {"checked_at": utc_now_iso(), "mode": "report-only", "status": status, "quality": quality, "sections": sections}
    if persist:
        _atomic_write(Path(config.paths.state_dir) / "audit" / "last-audit.json", result)
    return result
