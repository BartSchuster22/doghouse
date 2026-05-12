from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ExecutorActionPolicy(BaseModel):
    name: str
    argv: list[str]
    timeout_sec: int = 30
    destructive: bool = False
    requires_execute_flag: bool = False


class ExecutorPolicy(BaseModel):
    enabled: bool = False
    socket_path: str = "/run/doghouse-executor.sock"
    allowed_services: dict[str, str] = Field(default_factory=dict)
    allowed_actions: dict[str, ExecutorActionPolicy] = Field(default_factory=dict)
    restart_requires_service_policy: bool = True
    require_absolute_argv0: bool = True
    allowed_binaries: list[str] = Field(default_factory=lambda: ["/bin/systemctl", "/usr/bin/systemctl"])
    unit_name_regex: str = r"^[A-Za-z0-9_.@\-]+\.service$"
    audit_log_path: str = "/srv/shared-memory/logs/watchdog-v2/executor-audit.jsonl"
    restart_cooldown_sec: int = 300
    max_output_chars: int = 4000
    require_reason_for_destructive: bool = True
    min_destructive_reason_chars: int = 12
    require_confirmation_token_for_destructive: bool = True
    audit_include_hash_chain: bool = True


def default_policy() -> ExecutorPolicy:
    return ExecutorPolicy(
        enabled=False,
        allowed_actions={
            "systemctl_is_active": ExecutorActionPolicy(name="systemctl_is_active", argv=["/bin/systemctl", "is-active", "{unit}"], timeout_sec=10),
            "systemctl_show": ExecutorActionPolicy(name="systemctl_show", argv=["/bin/systemctl", "show", "{unit}", "--property=ActiveState,SubState,MainPID,NRestarts"], timeout_sec=10),
            "systemctl_restart": ExecutorActionPolicy(name="systemctl_restart", argv=["/bin/systemctl", "restart", "{unit}"], timeout_sec=60, destructive=True, requires_execute_flag=True),
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
