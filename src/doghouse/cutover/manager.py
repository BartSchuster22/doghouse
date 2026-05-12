from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from doghouse.common.config import DoghouseConfig, load_config_from_env
from doghouse.common.service_config import ServiceConfig, load_services
from doghouse.service_watchdog.checker import check_service
from doghouse.service_watchdog.state import utc_now_iso


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _run(argv: list[str], dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"argv": argv, "executed": False, "returncode": None, "stdout": "", "stderr": "", "reason": "dry run"}
    cp = subprocess.run(argv, text=True, capture_output=True, timeout=60, check=False)
    return {"argv": argv, "executed": True, "returncode": cp.returncode, "stdout": cp.stdout[-4000:], "stderr": cp.stderr[-4000:]}


def _load_service(service_id: str) -> ServiceConfig:
    services = load_services("/opt/doghouse/config/services.d") or load_services("config/services.d")
    for service in services:
        if service.service_id == service_id:
            return service
    raise ValueError(f"unknown service_id: {service_id}")


def cutover_service(service_id: str, config: DoghouseConfig | None = None, dry_run: bool = True) -> dict[str, Any]:
    config = config or load_config_from_env()
    service = _load_service(service_id)
    health = check_service(service, config, persist=True)
    timer = f"watchdog-{service_id}.timer"
    rollback = ["systemctl", "enable", "--now", timer]
    disable = ["systemctl", "disable", "--now", timer]
    result = {
        "checked_at": utc_now_iso(),
        "service_id": service_id,
        "dry_run": dry_run,
        "rollback_command": " ".join(rollback),
        "precheck": health.model_dump(mode="json"),
        "eligible": False,
        "actions": [],
    }
    if service.policy.report_only or not service.policy.restart_enabled:
        result["reason"] = "service policy has not enabled Doghouse restart"
    elif health.classification not in {"healthy", "degraded", "not_configured"}:
        result["reason"] = f"precheck not safe for cutover: {health.classification}"
    else:
        result["eligible"] = True
        result["actions"].append(_run(disable, dry_run=dry_run))
        result["actions"].append(_run(["systemctl", "daemon-reload"], dry_run=dry_run))
    _atomic_write(Path(config.paths.state_dir) / "cutover" / f"{service_id}.json", result)
    return result
