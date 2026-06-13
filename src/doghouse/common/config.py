from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ApiConfig(BaseModel):
    bind: str = "127.0.0.1"
    port: int = 18793
    auth_mode: str = "none-local-only"


class SchedulerConfig(BaseModel):
    service_interval_sec: int = 60
    devtask_interval_sec: int = 60
    audit_interval_sec: int = 300
    notification_interval_sec: int = 300
    notification_sweep_interval_sec: int = 900
    shadow_interval_sec: int = 300
    incident_reconcile_interval_sec: int = 300
    openclaw_readiness_interval_sec: int = 300
    daily_evidence_interval_sec: int = 86400
    daily_evidence_utc_hour: int = 6
    daily_evidence_utc_minute: int = 10


class PathsConfig(BaseModel):
    state_dir: str = "/state"
    incident_dir: str = "/incidents"
    log_dir: str = "/logs"
    checkpoint_dir: str = "/checkpoints"


class SafetyConfig(BaseModel):
    default_report_only: bool = True
    default_restart_enabled: bool = False
    default_kill_enabled: bool = False
    dedupe_window_sec: int = 1800


class HostExecutorConfig(BaseModel):
    enabled: bool = False
    policy_path: str = "/opt/doghouse/config/executor-policy.yaml"


class NotificationConfig(BaseModel):
    enabled: bool = True
    mode: str = "local_outbox"
    min_severity: str = "warning"
    outbox_path: str = "/srv/shared-memory/state/watchdog-v2/notifications/outbox.jsonl"
    latest_path: str = "/srv/shared-memory/state/watchdog-v2/notifications/latest.json"
    dedupe_window_sec: int = 1800


class DoghouseConfig(BaseModel):
    api: ApiConfig = Field(default_factory=ApiConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    host_executor: HostExecutorConfig = Field(default_factory=HostExecutorConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)


def load_config(path: str | os.PathLike[str]) -> DoghouseConfig:
    config_path = Path(path)
    if not config_path.exists():
        return DoghouseConfig()
    with config_path.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    return DoghouseConfig.model_validate(raw)


def load_config_from_env() -> DoghouseConfig:
    return load_config(os.environ.get("DOGHOUSE_CONFIG", "config/watchdog.yaml"))
