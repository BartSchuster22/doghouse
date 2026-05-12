from __future__ import annotations

from fastapi import APIRouter, Query

from doghouse.common.config import load_config_from_env
from doghouse.soak.report import generate_soak_report

router = APIRouter(prefix="/api/v1/soak", tags=["soak"])


@router.get("")
def soak_report(since: str = Query(default="24h")) -> dict:
    return generate_soak_report(load_config_from_env(), since=since, persist=True)
