from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class EndpointCheckResult(BaseModel):
    name: str
    url: str
    ok: bool
    status_code: int | None = None
    elapsed_ms: float | None = None
    error: str | None = None
    checked_at: str


class ServiceCheckResult(BaseModel):
    service_id: str
    display_name: str
    checked_at: str
    classification: str
    reason: str
    consecutive_liveness_failures: int
    failure_threshold: int
    report_only: bool
    restart_enabled: bool
    kill_enabled: bool
    endpoints: dict[str, EndpointCheckResult] = Field(default_factory=dict)
    diagnostics: dict[str, Any] | None = None
    incident: dict[str, Any] | None = None
    previous_state_path: str | None = None
    state_path: str | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def state_file(state_dir: str | Path, service_id: str) -> Path:
    return Path(state_dir) / "services" / f"{service_id}.json"


def read_previous_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_state_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
