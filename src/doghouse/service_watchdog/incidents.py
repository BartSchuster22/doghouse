from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doghouse.common.config import DoghouseConfig
from doghouse.common.service_config import ServiceConfig
from doghouse.service_watchdog.diagnostics import redact
from doghouse.service_watchdog.state import ServiceCheckResult, utc_now_iso

INCIDENT_CLASSIFICATIONS = {"degraded", "liveness_failed_threshold_met", "liveness_failed_below_threshold", "unknown"}


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def incident_key(service_id: str, classification: str, reason: str) -> str:
    # Dedupe by service + classification. Reasons can include counters/timings and should not defeat dedupe.
    digest = hashlib.sha256(f"{service_id}|{classification}".encode("utf-8")).hexdigest()[:16]
    return f"{service_id}-{classification}-{digest}"


def _dedupe_file(config: DoghouseConfig, key: str) -> Path:
    return Path(config.paths.state_dir) / "incident-dedupe" / f"{key}.json"


def should_emit_incident(config: DoghouseConfig, key: str, window_sec: int) -> tuple[bool, str | None]:
    path = _dedupe_file(config, key)
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            previous_at = _parse_iso(previous.get("last_emitted_at", ""))
            if previous_at:
                age = (datetime.now(timezone.utc) - previous_at).total_seconds()
                if age < window_sec:
                    return False, str(path)
        except (OSError, json.JSONDecodeError):
            pass
    return True, str(path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(redact(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Doghouse incident: {payload['service_id']} {payload['classification']}",
        "",
        f"Time: {payload['created_at']}",
        f"Incident ID: {payload['incident_id']}",
        f"Mode: {payload['mode']}",
        "",
        "## Reason",
        "",
        payload.get("reason", ""),
        "",
        "## Safety",
        "",
        f"- report_only: {payload['safety']['report_only']}",
        f"- restart_enabled: {payload['safety']['restart_enabled']}",
        f"- kill_enabled: {payload['safety']['kill_enabled']}",
        "",
        "## Diagnostics",
        "",
        "```json",
        json.dumps(payload.get("diagnostics", {}), indent=2, sort_keys=True),
        "```",
        "",
    ]
    return "\n".join(lines)


def maybe_write_incident(service: ServiceConfig, result: ServiceCheckResult, config: DoghouseConfig, diagnostics: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not service.incidents.enabled or result.classification == "healthy" or result.classification == "not_configured":
        return None
    key = incident_key(service.service_id, result.classification, result.reason)
    window = service.incidents.dedupe_window_sec or config.safety.dedupe_window_sec
    emit, dedupe_path = should_emit_incident(config, key, window)
    if not emit:
        return {"emitted": False, "deduped": True, "dedupe_path": dedupe_path, "incident_key": key}

    created_at = utc_now_iso()
    stamp = created_at.replace("-", "").replace(":", "").replace(".", "").replace("Z", "Z")
    incident_id = f"{stamp}-{service.service_id}-{result.classification}"
    base = Path(config.paths.incident_dir) / incident_id
    payload = {
        "incident_id": incident_id,
        "incident_key": key,
        "created_at": created_at,
        "service_id": service.service_id,
        "display_name": service.display_name,
        "classification": result.classification,
        "reason": result.reason,
        "mode": "report-only",
        "safety": {
            "report_only": result.report_only,
            "restart_enabled": result.restart_enabled,
            "kill_enabled": result.kill_enabled,
        },
        "check_result": result.model_dump(mode="json"),
        "diagnostics": diagnostics or {},
    }
    _write_json_atomic(base.with_suffix(".json"), payload)
    base.with_suffix(".md").write_text(_markdown(redact(payload)), encoding="utf-8")
    _write_json_atomic(_dedupe_file(config, key), {"last_emitted_at": created_at, "incident_id": incident_id, "incident_key": key})
    return {"emitted": True, "deduped": False, "incident_id": incident_id, "json_path": str(base.with_suffix(".json")), "md_path": str(base.with_suffix(".md")), "incident_key": key}


def list_recent_incidents(incident_dir: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    root = Path(incident_dir)
    if not root.exists():
        return []
    items = []
    for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append({
            "incident_id": data.get("incident_id", path.stem),
            "created_at": data.get("created_at"),
            "service_id": data.get("service_id"),
            "classification": data.get("classification"),
            "reason": data.get("reason"),
            "json_path": str(path),
            "md_path": str(path.with_suffix(".md")),
        })
    return items
