from __future__ import annotations

from fastapi import APIRouter

from doghouse.common.config import load_config_from_env
from doghouse.release.rc import build_release_candidate

router = APIRouter(prefix='/api/v1/release', tags=['release'])


@router.get('/candidate')
def get_release_candidate() -> dict:
    return build_release_candidate(load_config_from_env(), persist=True)


@router.post('/candidate/run')
def post_release_candidate() -> dict:
    return build_release_candidate(load_config_from_env(), persist=True)
