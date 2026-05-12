from pathlib import Path

from doghouse.common.service_config import ServiceConfig, ServicePolicy, RuntimeConfig
from doghouse.host_executor.executor import execute_host_action
from doghouse.host_executor.policy import ExecutorPolicy, ExecutorActionPolicy


def policy(tmp_path: Path) -> ExecutorPolicy:
    return ExecutorPolicy(
        enabled=True,
        allowed_services={"openclaw": "openclaw.service"},
        audit_log_path=str(tmp_path / "audit.jsonl"),
        allowed_actions={
            "systemctl_restart": ExecutorActionPolicy(name="systemctl_restart", argv=["/bin/systemctl", "restart", "{unit}"], destructive=True, requires_execute_flag=True),
            "systemctl_show": ExecutorActionPolicy(name="systemctl_show", argv=["/bin/systemctl", "show", "{unit}"], destructive=False),
        },
    )


def service() -> ServiceConfig:
    return ServiceConfig(service_id="openclaw", display_name="OpenClaw", runtime=RuntimeConfig(type="systemd", unit="openclaw.service"), policy=ServicePolicy(report_only=False, restart_enabled=True, kill_enabled=False))


def test_destructive_restart_requires_reason_and_confirmation(tmp_path):
    result = execute_host_action("systemctl_restart", service(), policy=policy(tmp_path), dry_run=False)
    assert result.allowed is False
    assert "reason" in result.reason
    result = execute_host_action("systemctl_restart", service(), policy=policy(tmp_path), dry_run=False, reason="operator requested restart")
    assert result.allowed is False
    assert "confirmation token" in result.reason


def test_executor_audit_hash_chain_for_denies(tmp_path):
    pol = policy(tmp_path)
    execute_host_action("missing_action", service(), policy=pol, dry_run=True)
    execute_host_action("missing_action", service(), policy=pol, dry_run=True)
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert '"audit_hash"' in lines[0]
    assert '"previous_audit_hash"' in lines[1]
