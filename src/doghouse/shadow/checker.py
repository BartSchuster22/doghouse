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


def _systemctl_is_enabled(unit: str) -> str:
    try:
        cp = subprocess.run(["systemctl", "is-enabled", unit], text=True, capture_output=True, timeout=10, check=False)
        return (cp.stdout or cp.stderr).strip() or f"rc={cp.returncode}"
    except Exception as exc:
        return f"error:{type(exc).__name__}:{exc}"


def shadow_once(config: DoghouseConfig | None = None, services_dir: str | Path | None = None, persist: bool = True) -> dict[str, Any]:
    config = config or load_config_from_env()
    root = Path(services_dir or ("/opt/doghouse/config/services.d" if Path("/opt/doghouse/config/services.d").exists() else "config/services.d"))
    services = load_services(root)
    items = []
    for service in services:
        result = check_service(service, config, persist=True)
        old_timer = f"watchdog-{service.service_id}.timer"
        old_enabled = _systemctl_is_enabled(old_timer)
        old_active = subprocess.run(["systemctl", "is-active", old_timer], text=True, capture_output=True, timeout=10, check=False)
        doghouse_would_restart = result.classification == "liveness_failed_threshold_met"
        old_watchdog_present = Path(f"/etc/systemd/system/{old_timer}").exists()
        mismatch = False
        notes = []
        if doghouse_would_restart and service.policy.report_only:
            notes.append("doghouse would restart only if report_only=false and restart_enabled=true")
        if old_watchdog_present and "enabled" in old_enabled and service.policy.restart_enabled:
            mismatch = True
            notes.append("old watchdog still enabled while doghouse restart is enabled")
        items.append({
            "service_id": service.service_id,
            "classification": result.classification,
            "reason": result.reason,
            "doghouse_would_restart": doghouse_would_restart,
            "doghouse_report_only": service.policy.report_only,
            "doghouse_restart_enabled": service.policy.restart_enabled,
            "old_timer": old_timer,
            "old_timer_file_exists": old_watchdog_present,
            "old_timer_enabled": old_enabled,
            "old_timer_active": (old_active.stdout or old_active.stderr).strip() or f"rc={old_active.returncode}",
            "mismatch": mismatch,
            "notes": notes,
        })
    status = "attention" if any(item["mismatch"] for item in items) else "ok"
    result = {"checked_at": utc_now_iso(), "status": status, "mode": "shadow", "items": items}
    if persist:
        _atomic_write(Path(config.paths.state_dir) / "shadow" / "last-shadow-report.json", result)
        _atomic_write(Path(config.paths.incident_dir) / f"{utc_now_iso().replace(':','').replace('-','')}-doghouse-shadow-report.json", result)
    return result
