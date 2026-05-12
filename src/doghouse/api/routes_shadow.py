from __future__ import annotations

from fastapi import APIRouter

from doghouse.common.config import load_config_from_env
from doghouse.shadow.checker import shadow_once

router = APIRouter(prefix="/api/v1/shadow", tags=["shadow"])


@router.get("")
def get_shadow() -> dict:
    return shadow_once(load_config_from_env(), persist=False)


@router.post("/run")
def run_shadow() -> dict:
    return shadow_once(load_config_from_env(), persist=True)
