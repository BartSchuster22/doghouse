from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class RuntimeConfig(BaseModel):
    type: str = "http_only"
    unit: str | None = None
    container: str | None = None


class ServicePolicy(BaseModel):
    report_only: bool = True
    restart_enabled: bool = False
    kill_enabled: bool = False
    failure_threshold: int = 3
    timeout_sec: int = 10
    startup_grace_sec: int = 90
    restart_settle_sec: int = 15
    active_task_guard: bool = True
    active_task_query_failure_policy: Literal["defer", "ignore", "manual"] = "defer"


class IncidentPolicy(BaseModel):
    enabled: bool = True
    dedupe_window_sec: int = 1800


class ExtraCheckConfig(BaseModel):
    id: str
    type: str
    restart_grade: bool = False
    degraded_threshold: int = 3
    config: dict[str, Any] = Field(default_factory=dict)


class ServiceConfig(BaseModel):
    service_id: str
    display_name: str
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    endpoints: dict[str, str] = Field(default_factory=dict)
    policy: ServicePolicy = Field(default_factory=ServicePolicy)
    incidents: IncidentPolicy = Field(default_factory=IncidentPolicy)
    extra_checks: list[ExtraCheckConfig] = Field(default_factory=list)


def load_service_config(path: Path) -> ServiceConfig:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return ServiceConfig.model_validate(raw)


def load_services(config_dir: str | Path) -> list[ServiceConfig]:
    root = Path(config_dir)
    if not root.exists():
        return []
    services = [load_service_config(path) for path in sorted(root.glob("*.yaml"))]
    return services
