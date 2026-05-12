from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doghouse.common.config import DoghouseConfig
from doghouse.common.service_config import load_services
from doghouse.service_watchdog.checker import check_service
from doghouse.service_watchdog.state import utc_now_iso
from doghouse.shadow.checker import shadow_once


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _move_pair(path: Path, target_dir: Path, reason: str) -> dict[str, Any]:
    target_dir.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for src in [path, path.with_suffix(".md")]:
        if not src.exists():
            continue
        dest = target_dir / src.name
        if dest.exists():
            dest = target_dir / f"{src.stem}-{os.getpid()}{src.suffix}"
        shutil.move(str(src), str(dest))
        moved.append(str(dest))
    return {"source": str(path), "target_dir": str(target_dir), "reason": reason, "moved": moved}


def reconcile_open_incidents(config: DoghouseConfig, persist: bool = True) -> dict[str, Any]:
    """Close non-actionable open records without deleting evidence.

    Phase 31 distinguishes true open incidents from archival evidence. Earlier
    shadow mode wrote every ok shadow report into the open incident directory;
    recovered one-shot below-threshold service incidents can also remain open
    after the service is healthy. This reconciler moves those records out of
    incidents/open and into resolved archive folders, preserving files and a
    reconciliation manifest.
    """
    incident_dir = Path(config.paths.incident_dir)
    state_dir = Path(config.paths.state_dir)
    services = load_services("/opt/doghouse/config/services.d") or load_services("config/services.d")
    current: dict[str, dict[str, Any]] = {}
    for service in services:
        result = check_service(service, config, persist=True).model_dump(mode="json")
        current[service.service_id] = result
    shadow_now = shadow_once(config, persist=True)

    actions: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    if incident_dir.exists():
        for path in sorted(incident_dir.glob("*.json")):
            payload = _read_json(path) or {}
            name = path.name
            if name.endswith("-doghouse-shadow-report.json") or name.endswith("-doghouse-shadow-attention.json"):
                if payload.get("status") == "ok":
                    actions.append(_move_pair(path, state_dir / "shadow" / "archive" / "misfiled-open-incidents", "ok_shadow_report_misfiled_as_incident"))
                    continue
                if shadow_now.get("status") == "ok":
                    actions.append(_move_pair(path, state_dir / "shadow" / "archive" / "resolved-attention", "shadow_attention_resolved_current_shadow_ok"))
                    continue
                remaining.append({"path": str(path), "kind": "shadow_attention", "status": payload.get("status")})
                continue

            if "watchdog-" in name and payload.get("service_id") is None:
                actions.append(_move_pair(path, incident_dir.parent / "resolved" / _stamp(), "legacy_watchdog_record_after_doghouse_cutover"))
                continue

            service_id = payload.get("service_id")
            classification = payload.get("classification")
            service_now = current.get(service_id or "")
            if service_now and service_now.get("classification") == "healthy" and classification in {"liveness_failed_below_threshold", "liveness_failed_threshold_met", "degraded"}:
                actions.append(_move_pair(path, incident_dir.parent / "resolved" / _stamp(), "service_recovered_and_currently_healthy"))
                continue
            remaining.append({
                "path": str(path),
                "service_id": service_id,
                "classification": classification,
                "current_classification": (service_now or {}).get("classification"),
            })

    report = {
        "generated_at": utc_now_iso(),
        "status": "ok" if not remaining else "attention",
        "actions_count": len(actions),
        "remaining_open_count": len(remaining),
        "actions": actions,
        "remaining_open": remaining,
        "current_service_status": {sid: item.get("classification") for sid, item in current.items()},
    }
    if persist:
        out = state_dir / "incidents" / "latest-reconciliation.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, out)
        report["path"] = str(out)
    return report
