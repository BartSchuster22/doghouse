from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from doghouse.common.config import DoghouseConfig
from doghouse.common.service_config import load_services
from doghouse.service_watchdog.state import utc_now_iso


def _parse_since(value: str) -> tuple[str, datetime]:
    raw = (value or "24h").strip().lower()
    now = datetime.now(timezone.utc)
    if raw.endswith("h") and raw[:-1].isdigit():
        hours = int(raw[:-1])
        return f"{hours} hours ago", now - timedelta(hours=hours)
    if raw.endswith("d") and raw[:-1].isdigit():
        days = int(raw[:-1])
        return f"{days} days ago", now - timedelta(days=days)
    return value, now - timedelta(hours=24)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _journal_summary(units: list[str], since_systemd: str) -> dict[str, Any]:
    if not units:
        return {"available": False, "reason": "no units"}
    argv = ["journalctl"]
    for unit in units:
        argv.extend(["-u", unit])
    argv.extend(["--since", since_systemd, "--no-pager", "-o", "short-iso"])
    try:
        cp = subprocess.run(argv, text=True, capture_output=True, timeout=30, check=False)
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    text = (cp.stdout or "") + (cp.stderr or "")
    lines = [line for line in text.splitlines() if line.strip()]
    permission_limited = any("not seeing messages" in line or "not opened due to insufficient permissions" in line for line in lines)
    success_lines = [line for line in lines if "status=0/SUCCESS" in line or "Finished Doghouse" in line]
    failure_lines = [line for line in lines if "status=1/" in line or "failed" in line.lower() or "traceback" in line.lower()]
    restart_lines = [line for line in lines if "systemctl_restart" in line or "restart" in line.lower()]
    return {
        "available": cp.returncode == 0 and not permission_limited,
        "returncode": cp.returncode,
        "permission_limited": permission_limited,
        "line_count": len(lines),
        "success_line_count": len(success_lines),
        "failure_line_count": len(failure_lines),
        "restart_line_count": len(restart_lines),
        "recent_failures": failure_lines[-10:],
        "recent_restarts": restart_lines[-10:],
    }


def _incident_summary(incident_dir: Path, since_dt: datetime) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    if incident_dir.exists():
        for path in sorted(incident_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                if datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) < since_dt:
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
                items.append({
                    "path": str(path),
                    "service_id": payload.get("service_id"),
                    "classification": payload.get("classification"),
                    "created_at": payload.get("created_at") or payload.get("checked_at"),
                })
            except Exception:
                continue
    return {"count": len(items), "items": items[:25]}


def generate_soak_report(config: DoghouseConfig, since: str = "24h", persist: bool = True) -> dict[str, Any]:
    since_systemd, since_dt = _parse_since(since)
    services = load_services("/opt/doghouse/config/services.d") or load_services("config/services.d")
    service_ids = [service.service_id for service in services]
    state_dir = Path(config.paths.state_dir)
    latest_states: dict[str, Any] = {}
    for service_id in service_ids:
        latest_states[service_id] = _read_json(state_dir / "services" / f"{service_id}.json") or {"exists": False}
    shadow = _read_json(state_dir / "shadow" / "last-shadow-report.json")
    audit = _read_json(state_dir / "audit" / "latest.json")
    units = [f"doghouse-check@{service_id}.service" for service_id in service_ids]
    units.append("doghouse-shadow.service")
    journal = _journal_summary(units, since_systemd)
    incidents = _incident_summary(Path(config.paths.incident_dir), since_dt)
    unhealthy = [sid for sid, state in latest_states.items() if state.get("classification") not in {"healthy", "not_configured"}]
    restart_actions = [sid for sid, state in latest_states.items() if (state.get("action") or {}).get("executed")]
    status = "ok"
    attention: list[str] = []
    if unhealthy:
        status = "attention"
        attention.append(f"unhealthy_or_degraded_services={','.join(unhealthy)}")
    if incidents["count"]:
        status = "attention"
        attention.append(f"incidents_in_window={incidents['count']}")
    if journal.get("failure_line_count", 0):
        status = "attention"
        attention.append(f"journal_failures={journal['failure_line_count']}")
    if restart_actions:
        status = "attention"
        attention.append(f"restart_actions_executed={','.join(restart_actions)}")
    report = {
        "generated_at": utc_now_iso(),
        "since": since,
        "since_systemd": since_systemd,
        "status": status,
        "attention": attention,
        "service_ids": service_ids,
        "latest_states": latest_states,
        "shadow": shadow,
        "audit": audit,
        "journal": journal,
        "incidents": incidents,
        "restart_actions": restart_actions,
    }
    if persist:
        out = state_dir / "soak" / "latest-soak-report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(out)
        report["path"] = str(out)
    return report
