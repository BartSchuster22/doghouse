from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from doghouse.common.config import DoghouseConfig
from doghouse.common.service_config import load_services
from doghouse.service_watchdog.checker import check_endpoint, check_service
from doghouse.service_watchdog.state import utc_now_iso


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _systemctl_is_active(unit: str) -> dict[str, Any]:
    try:
        cp = subprocess.run(["/bin/systemctl", "is-active", unit], text=True, capture_output=True, timeout=10, check=False)
        return {"unit": unit, "active": cp.returncode == 0, "returncode": cp.returncode, "stdout": cp.stdout.strip(), "stderr": cp.stderr.strip()}
    except FileNotFoundError:
        return {"unit": unit, "active": False, "status": "unavailable", "error": "systemctl unavailable"}
    except Exception as exc:
        return {"unit": unit, "active": False, "error": f"{type(exc).__name__}: {exc}"}


def _report_only_service(service):
    return service.model_copy(
        deep=True,
        update={
            "policy": service.policy.model_copy(
                update={"report_only": True, "restart_enabled": False, "kill_enabled": False}
            )
        },
    )


def check_openclaw_readiness(config: DoghouseConfig, persist: bool = True, *, report_only: bool = False) -> dict[str, Any]:
    services = load_services("/opt/doghouse/config/services.d") or load_services("config/services.d")
    matches = [s for s in services if s.service_id == "openclaw"]
    if not matches:
        result = {"checked_at": utc_now_iso(), "service_id": "openclaw", "status": "fail", "reason": "openclaw service config missing"}
    else:
        svc = matches[0]
        service_check_svc = _report_only_service(svc) if report_only else svc
        endpoints = {name: check_endpoint(name, url, svc.policy.timeout_sec).model_dump(mode="json") for name, url in svc.endpoints.items() if name in {"live", "ready", "health", "active_work"}}
        service_check = check_service(service_check_svc, config, persist=True).model_dump(mode="json")
        unit = _systemctl_is_active(svc.runtime.unit or "openclaw.service")
        old_timer = _systemctl_is_active("watchdog-openclaw.timer")
        doghouse_timer = _systemctl_is_active("doghouse-check@openclaw.timer")
        systemctl_available = all(item.get("status") != "unavailable" for item in (unit, old_timer, doghouse_timer))
        endpoint_ok = all(item.get("ok") is True for item in endpoints.values())
        policy_ok = svc.policy.restart_enabled and not svc.policy.report_only and not svc.policy.kill_enabled and svc.policy.active_task_guard
        timers_ok = doghouse_timer.get("active") is True and old_timer.get("active") is False
        status = "ready" if unit.get("active") and endpoint_ok and service_check.get("classification") == "healthy" and policy_ok and timers_ok else "attention"
        result = {
            "checked_at": utc_now_iso(),
            "service_id": "openclaw",
            "status": status,
            "unit": unit,
            "old_watchdog_timer": old_timer,
            "doghouse_timer": doghouse_timer,
            "policy": svc.policy.model_dump(mode="json"),
            "endpoint_modes": svc.endpoint_modes,
            "endpoints": endpoints,
            "service_check": service_check,
            "requirements": {
                "unit_active": unit.get("active") is True,
                "endpoints_ok": endpoint_ok,
                "doghouse_classifies_healthy": service_check.get("classification") == "healthy",
                "policy_cutover_safe": policy_ok,
                "timers_cutover_safe": timers_ok,
                "systemctl_available": systemctl_available,
            },
        }
    if persist:
        _atomic_write(Path(config.paths.state_dir) / "readiness" / "openclaw.json", result)
    return result
