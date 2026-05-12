from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from doghouse.audit.checker import run_audit
from doghouse.common.config import load_config_from_env

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("")
def audit_status() -> dict:
    cfg = load_config_from_env()
    path = Path(cfg.paths.state_dir) / "audit" / "last-audit.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"status": "state_unreadable", "state_path": str(path), "error": f"{type(exc).__name__}: {exc}"}
    return {"status": "not_checked_yet", "state_path": str(path)}


@router.post("/run")
def run_audit_now() -> dict:
    return run_audit(load_config_from_env(), persist=True)
