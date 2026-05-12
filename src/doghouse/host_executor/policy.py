from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ExecutorActionPolicy(BaseModel):
    name: str
    argv: list[str]
    timeout_sec: int = 30


class ExecutorPolicy(BaseModel):
    enabled: bool = False
    socket_path: str = "/run/doghouse-executor.sock"
    allowed_services: dict[str, str] = Field(default_factory=dict)
    allowed_actions: dict[str, ExecutorActionPolicy] = Field(default_factory=dict)
    restart_requires_service_policy: bool = True


def default_policy() -> ExecutorPolicy:
    return ExecutorPolicy(
        enabled=False,
        allowed_actions={
            "systemctl_is_active": ExecutorActionPolicy(name="systemctl_is_active", argv=["systemctl", "is-active", "{unit}"], timeout_sec=10),
            "systemctl_show": ExecutorActionPolicy(name="systemctl_show", argv=["systemctl", "show", "{unit}", "--property=ActiveState,SubState,MainPID,NRestarts"], timeout_sec=10),
            "systemctl_restart": ExecutorActionPolicy(name="systemctl_restart", argv=["systemctl", "restart", "{unit}"], timeout_sec=60),
        },
    )


def load_executor_policy(path: str | Path) -> ExecutorPolicy:
    policy_path = Path(path)
    if not policy_path.exists():
        return default_policy()
    raw: dict[str, Any] = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    merged = default_policy().model_dump(mode="json")
    for key, value in raw.items():
        if key == "allowed_actions":
            merged[key].update(value or {})
        else:
            merged[key] = value
    return ExecutorPolicy.model_validate(merged)
