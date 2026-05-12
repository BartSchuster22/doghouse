from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Query

from doghouse.common.config import load_config_from_env
from pydantic import BaseModel

from doghouse.devtask_watchdog.checker import check_devtasks, prune_completed_heartbeats, read_heartbeats, write_heartbeat

router = APIRouter(prefix="/api/v1/devtasks", tags=["devtasks"])


class HeartbeatRequest(BaseModel):
    task_id: str
    status: str = "active"
    progress: str | None = None
    pid: int | None = None
    metadata: dict = {}


@router.get("/heartbeats")
def list_heartbeats() -> list[dict]:
    return read_heartbeats(load_config_from_env())


@router.post("/heartbeats")
def submit_heartbeat(req: HeartbeatRequest) -> dict:
    return write_heartbeat(load_config_from_env(), req.task_id, status=req.status, progress=req.progress, pid=req.pid, metadata=req.metadata)


@router.post("/heartbeats/prune")
def prune_heartbeats(max_age_sec: int = Query(default=86400)) -> dict:
    return prune_completed_heartbeats(load_config_from_env(), max_age_sec=max_age_sec)


@router.get("/status")
def devtask_status() -> dict:
    cfg = load_config_from_env()
    path = Path(cfg.paths.state_dir) / "devtasks" / "last-check.json"
    if not path.exists():
        return {"classification": "not_checked_yet", "state_path": str(path), "kill_enabled": False, "interrupt_enabled": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"classification": "state_unreadable", "state_path": str(path), "error": f"{type(exc).__name__}: {exc}", "kill_enabled": False, "interrupt_enabled": False}


@router.post("/check")
def run_devtask_check(active_work_url: str | None = Query(default=None)) -> dict:
    return check_devtasks(load_config_from_env(), active_work_url=active_work_url, persist=True)
