from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from doghouse.common.config import load_config_from_env
from doghouse.notifications.notifier import notification_status, notify_event

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class NotificationRequest(BaseModel):
    source: str = "operator"
    severity: str = "info"
    title: str
    summary: str
    status: str | None = None
    details: dict = {}
    force: bool = False


@router.get("/status")
def status() -> dict:
    return notification_status(load_config_from_env())


@router.post("/send")
def send(req: NotificationRequest) -> dict:
    return notify_event(req.source, req.severity, req.title, req.summary, status=req.status, details=req.details, config=load_config_from_env(), force=req.force)


@router.post("/test")
def test() -> dict:
    return notify_event("notification_test", "warning", "Doghouse notification test", "Local outbox notification path is working", status="test", config=load_config_from_env(), force=True)
