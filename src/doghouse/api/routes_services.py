from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from doghouse.common.service_config import ServiceConfig, load_services

router = APIRouter(prefix="/api/v1/services", tags=["services"])


def _services_dir() -> Path:
    # Config is currently file-based. This keeps Phase 1 simple and explicit.
    return Path("/opt/doghouse/config/services.d") if Path("/opt/doghouse/config/services.d").exists() else Path("config/services.d")


@router.get("")
def list_services() -> list[dict]:
    return [service.model_dump() for service in load_services(_services_dir())]


@router.get("/{service_id}")
def get_service(service_id: str) -> dict:
    for service in load_services(_services_dir()):
        if service.service_id == service_id:
            return service.model_dump()
    raise HTTPException(status_code=404, detail=f"unknown service_id: {service_id}")


@router.get("/{service_id}/status")
def get_service_status(service_id: str) -> dict:
    for service in load_services(_services_dir()):
        if service.service_id == service_id:
            return {
                "service_id": service.service_id,
                "display_name": service.display_name,
                "classification": "not_checked_yet",
                "mode": "report-only",
                "restart_enabled": service.policy.restart_enabled,
                "kill_enabled": service.policy.kill_enabled,
                "configured_endpoints": sorted(service.endpoints.keys()),
            }
    raise HTTPException(status_code=404, detail=f"unknown service_id: {service_id}")
