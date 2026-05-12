from __future__ import annotations

from fastapi import APIRouter

from doghouse.common.config import load_config_from_env
from doghouse.drills.restart import run_restart_drill

router = APIRouter(prefix='/api/v1/drills', tags=['drills'])


@router.get('/restart/{service_id}')
def get_restart_drill(service_id: str) -> dict:
    return run_restart_drill(service_id, load_config_from_env(), execute=False, persist=True)


@router.post('/restart/{service_id}/run')
def post_restart_drill(service_id: str, execute: bool = False, reason: str | None = None) -> dict:
    return run_restart_drill(service_id, load_config_from_env(), execute=execute, reason=reason, persist=True)
