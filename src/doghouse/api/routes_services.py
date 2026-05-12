from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from doghouse.common.config import load_config_from_env
from doghouse.common.service_config import ServiceConfig, load_services
from doghouse.service_watchdog.checker import check_service
from doghouse.service_watchdog.state import read_previous_state, state_file

router = APIRouter(prefix="/api/v1/services", tags=["services"])


def _services_dir() -> Path:
    # Config is currently file-based. This keeps Phase 1 simple and explicit.
    return Path("/opt/doghouse/config/services.d") if Path("/opt/doghouse/config/services.d").exists() else Path("config/services.d")


def _get_service_or_404(service_id: str) -> ServiceConfig:
    for service in load_services(_services_dir()):
        if service.service_id == service_id:
            return service
    raise HTTPException(status_code=404, detail=f"unknown service_id: {service_id}")


@router.get("")
def list_services() -> list[dict]:
    return [service.model_dump() for service in load_services(_services_dir())]


@router.get("/{service_id}")
def get_service(service_id: str) -> dict:
    return _get_service_or_404(service_id).model_dump()


@router.get("/{service_id}/status")
def get_service_status(service_id: str) -> dict:
    service = _get_service_or_404(service_id)
    cfg = load_config_from_env()
    path = state_file(cfg.paths.state_dir, service.service_id)
    previous = read_previous_state(path)
    if previous:
        return previous
    return {
        "service_id": service.service_id,
        "display_name": service.display_name,
        "classification": "not_checked_yet",
        "reason": "no persisted Phase 2 check result exists yet",
        "mode": "report-only",
        "restart_enabled": service.policy.restart_enabled,
        "kill_enabled": service.policy.kill_enabled,
        "configured_endpoints": sorted(service.endpoints.keys()),
        "state_path": str(path),
    }


@router.post("/{service_id}/check")
def run_service_check(service_id: str) -> dict:
    service = _get_service_or_404(service_id)
    return check_service(service, load_config_from_env(), persist=True).model_dump(mode="json")
