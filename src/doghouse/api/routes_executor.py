from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from doghouse.common.service_config import load_services
from doghouse.host_executor.executor import execute_host_action
from doghouse.host_executor.policy import load_executor_policy

router = APIRouter(prefix="/api/v1/executor", tags=["executor"])


class ExecuteRequest(BaseModel):
    action: str
    dry_run: bool = True
    reason: str | None = None
    confirmation_token: str | None = None


@router.get("/policy")
def policy() -> dict:
    return load_executor_policy("/opt/doghouse/config/executor-policy.yaml").model_dump(mode="json")


@router.post("/services/{service_id}/execute")
def execute(service_id: str, request: ExecuteRequest) -> dict:
    services = load_services("/opt/doghouse/config/services.d") or load_services("config/services.d")
    matches = [item for item in services if item.service_id == service_id]
    if not matches:
        raise HTTPException(status_code=404, detail="unknown service_id")
    return execute_host_action(request.action, matches[0], dry_run=request.dry_run, reason=request.reason, confirmation_token=request.confirmation_token).as_dict()
