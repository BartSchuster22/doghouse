from __future__ import annotations

from fastapi import APIRouter, Query

from doghouse.common.config import load_config_from_env
from doghouse.service_watchdog.incidents import list_recent_incidents
from doghouse.service_watchdog.reconcile import reconcile_open_incidents

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.get("")
def recent_incidents(limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
    cfg = load_config_from_env()
    return list_recent_incidents(cfg.paths.incident_dir, limit=limit)


@router.post("/reconcile")
def reconcile_incidents() -> dict:
    return reconcile_open_incidents(load_config_from_env(), persist=True)
