from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doghouse.common.config import DoghouseConfig, load_config_from_env

SEVERITY_ORDER = {"info": 10, "warning": 20, "critical": 30}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _event_key(payload: dict[str, Any]) -> str:
    material = json.dumps({
        "source": payload.get("source"),
        "severity": payload.get("severity"),
        "status": payload.get("status"),
        "title": payload.get("title"),
        "summary": payload.get("summary"),
    }, sort_keys=True)
    return hashlib.sha256(material.encode()).hexdigest()[:24]


def _recent_duplicate(outbox: Path, event_key: str, dedupe_window_sec: int) -> bool:
    if not outbox.exists():
        return False
    cutoff = datetime.now(timezone.utc).timestamp() - dedupe_window_sec
    try:
        lines = outbox.read_text(encoding="utf-8").splitlines()[-200:]
    except OSError:
        return False
    for line in reversed(lines):
        try:
            item = json.loads(line)
            created = datetime.fromisoformat(str(item.get("created_at", "")).replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if created < cutoff:
            break
        if item.get("event_key") == event_key:
            return True
    return False


def notify_event(source: str, severity: str, title: str, summary: str, status: str | None = None, details: dict[str, Any] | None = None, config: DoghouseConfig | None = None, force: bool = False) -> dict[str, Any]:
    config = config or load_config_from_env()
    severity = severity if severity in SEVERITY_ORDER else "info"
    min_sev = config.notifications.min_severity if config.notifications.min_severity in SEVERITY_ORDER else "warning"
    payload: dict[str, Any] = {
        "created_at": utc_now_iso(),
        "source": source,
        "severity": severity,
        "status": status,
        "title": title,
        "summary": summary,
        "details": details or {},
        "mode": config.notifications.mode,
        "delivered": False,
    }
    payload["event_key"] = _event_key(payload)
    if not config.notifications.enabled:
        payload.update({"accepted": False, "reason": "notifications disabled"})
        return payload
    if not force and SEVERITY_ORDER[severity] < SEVERITY_ORDER[min_sev]:
        payload.update({"accepted": False, "reason": f"severity below min_severity {min_sev}"})
        return payload
    outbox = Path(config.notifications.outbox_path)
    latest = Path(config.notifications.latest_path)
    if not force and _recent_duplicate(outbox, payload["event_key"], config.notifications.dedupe_window_sec):
        payload.update({"accepted": False, "deduped": True, "reason": "duplicate inside dedupe window"})
        _atomic_write(latest, payload)
        return payload
    outbox.parent.mkdir(parents=True, exist_ok=True)
    with outbox.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({**payload, "accepted": True}, sort_keys=True) + "\n")
    payload.update({"accepted": True, "outbox_path": str(outbox)})
    _atomic_write(latest, payload)
    return payload


def notify_from_audit(audit: dict[str, Any], config: DoghouseConfig | None = None, force: bool = False) -> dict[str, Any]:
    status = str(audit.get("status") or "unknown")
    severity = "critical" if status == "attention" else "info"
    sections = audit.get("sections", {}) if isinstance(audit.get("sections"), dict) else {}
    bad = [name for name, section in sections.items() if isinstance(section, dict) and section.get("status") not in {"ok", "inventory"}]
    return notify_event("audit", severity, f"Doghouse audit {status}", f"Attention sections: {', '.join(bad) if bad else 'none'}", status=status, details={"attention_sections": bad}, config=config, force=force)


def notify_from_qa(qa: dict[str, Any], config: DoghouseConfig | None = None, force: bool = False) -> dict[str, Any]:
    status = str(qa.get("status") or "unknown")
    score = qa.get("score")
    severity = "warning" if status != "pass" else "info"
    return notify_event("qa_gate", severity, f"Doghouse QA gate {status}", f"Score: {score}/10", status=status, details={"score": score, "failed_items": qa.get("failed_items", [])}, config=config, force=force)


def notification_status(config: DoghouseConfig | None = None) -> dict[str, Any]:
    config = config or load_config_from_env()
    outbox = Path(config.notifications.outbox_path)
    latest = Path(config.notifications.latest_path)
    return {
        "enabled": config.notifications.enabled,
        "mode": config.notifications.mode,
        "min_severity": config.notifications.min_severity,
        "outbox_path": str(outbox),
        "outbox_exists": outbox.exists(),
        "outbox_events": len(outbox.read_text(encoding="utf-8").splitlines()) if outbox.exists() else 0,
        "latest_path": str(latest),
        "latest_exists": latest.exists(),
    }
