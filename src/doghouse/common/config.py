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


class DoghouseConfig(BaseModel):
    api: ApiConfig = Field(default_factory=ApiConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    host_executor: HostExecutorConfig = Field(default_factory=HostExecutorConfig)


def load_config(path: str | os.PathLike[str]) -> DoghouseConfig:
    config_path = Path(path)
    if not config_path.exists():
        return DoghouseConfig()
    with config_path.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    return DoghouseConfig.model_validate(raw)


def load_config_from_env() -> DoghouseConfig:
    return load_config(os.environ.get("DOGHOUSE_CONFIG", "config/watchdog.yaml"))
