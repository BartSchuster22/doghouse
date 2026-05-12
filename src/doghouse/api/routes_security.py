from __future__ import annotations

from fastapi import APIRouter

from doghouse.common.config import load_config_from_env
from doghouse.security.review import run_security_review

router = APIRouter(prefix='/api/v1/security', tags=['security'])


@router.get('/review')
def get_security_review() -> dict:
    return run_security_review(load_config_from_env(), persist=True)


@router.post('/review/run')
def post_security_review() -> dict:
    return run_security_review(load_config_from_env(), persist=True)
