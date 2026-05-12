from __future__ import annotations

from fastapi import APIRouter

from doghouse.common.config import load_config_from_env
from doghouse.readiness.openclaw import check_openclaw_readiness

router = APIRouter(prefix="/api/v1/readiness", tags=["readiness"])


@router.get("/openclaw")
def openclaw_latest() -> dict:
    return check_openclaw_readiness(load_config_from_env(), persist=False)


@router.post("/openclaw/run")
def openclaw_run() -> dict:
    return check_openclaw_readiness(load_config_from_env(), persist=True)
