from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doghouse.common.config import DoghouseConfig, load_config_from_env
from doghouse.common.service_config import ServiceConfig, load_services
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
                    item.update({"checked_at": data.get("checked_at"), "age_sec": int(age), "fresh": age <= max_age})
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


def check_old_watchdog_migration(services: list[ServiceConfig]) -> dict[str, Any]:
    items = []
    for service in services:
        unit = service.runtime.unit or f"{service.service_id}.service"
        timer = Path(f"/etc/systemd/system/watchdog-{service.service_id}.timer")
        svc = Path(f"/etc/systemd/system/watchdog-{service.service_id}.service")
        items.append({
            "service_id": service.service_id,
            "runtime_unit": unit,
            "old_timer_path": str(timer),
            "old_timer_file_exists": timer.exists(),
            "old_service_path": str(svc),
            "old_service_file_exists": svc.exists(),
            "cutover_state": "old-watchdog-file-present" if timer.exists() or svc.exists() else "no-old-watchdog-file-detected",
            "doghouse_restart_enabled": service.policy.restart_enabled,
        })
    return {"status": "inventory", "items": items, "note": "file inventory only; Phase 5 does not disable old timers or cut over services"}


def run_audit(config: DoghouseConfig | None = None, services_dir: str | Path | None = None, persist: bool = True) -> dict[str, Any]:
    config = config or load_config_from_env()
    root = Path(services_dir or ("/opt/doghouse/config/services.d" if Path("/opt/doghouse/config/services.d").exists() else "config/services.d"))
    services = load_services(root)
    sections = {
        "scheduler_freshness": check_scheduler_freshness(config, services),
        "policy": check_policy(services, config),
        "paths": check_paths(config),
        "old_watchdog_migration": check_old_watchdog_migration(services),
    }
    status = "ok" if all(section.get("status") in {"ok", "inventory"} for section in sections.values()) else "attention"
    result = {"checked_at": utc_now_iso(), "mode": "report-only", "status": status, "sections": sections}
    if persist:
        _atomic_write(Path(config.paths.state_dir) / "audit" / "last-audit.json", result)
    return result
