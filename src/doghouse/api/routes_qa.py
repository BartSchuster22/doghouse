from __future__ import annotations

from fastapi import APIRouter, Query

from doghouse.common.config import load_config_from_env
from doghouse.evidence.daily import generate_daily_evidence
from doghouse.qa.gate import run_qa_gate

router = APIRouter(prefix="/api/v1/qa", tags=["qa"])


@router.get("/gate")
def qa_gate(threshold: float = Query(default=8.0)) -> dict:
    return run_qa_gate(load_config_from_env(), threshold=threshold, persist=True)


@router.post("/gate/run")
def qa_gate_run(threshold: float = Query(default=8.0)) -> dict:
    return run_qa_gate(load_config_from_env(), threshold=threshold, persist=True)


@router.get("/evidence/daily")
def daily_evidence(since: str = Query(default="24h"), threshold: float = Query(default=8.0)) -> dict:
    return generate_daily_evidence(load_config_from_env(), since=since, threshold=threshold, persist=True)


@router.post("/evidence/daily/run")
def daily_evidence_run(since: str = Query(default="24h"), threshold: float = Query(default=8.0)) -> dict:
    return generate_daily_evidence(load_config_from_env(), since=since, threshold=threshold, persist=True)
