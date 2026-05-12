from pathlib import Path

from doghouse.common.config import DoghouseConfig, HostExecutorConfig, PathsConfig
from doghouse.common.service_config import ServiceConfig, ServicePolicy, RuntimeConfig
from doghouse.drills import restart as restart_mod
from doghouse.security.review import run_security_review
from doghouse.host_executor.policy import ExecutorActionPolicy, ExecutorPolicy
from doghouse.service_watchdog import reconcile as reconcile_mod


def test_security_review_passes_hardened_executor_policy(tmp_path, monkeypatch):
    policy_path = tmp_path / "executor-policy.yaml"
    policy_path.write_text(
        """
enabled: true
restart_requires_service_policy: true
require_absolute_argv0: true
allowed_binaries: [/bin/systemctl, /usr/bin/systemctl]
unit_name_regex: '^[A-Za-z0-9_.@\\-]+\\.service$'
audit_log_path: /tmp/doghouse-audit.jsonl
restart_cooldown_sec: 300
require_reason_for_destructive: true
min_destructive_reason_chars: 12
require_confirmation_token_for_destructive: true
audit_include_hash_chain: true
allowed_services:
  hermes: hermes.service
allowed_actions:
  systemctl_restart:
    name: systemctl_restart
    argv: [/bin/systemctl, restart, "{unit}"]
    timeout_sec: 60
    destructive: true
    requires_execute_flag: true
""",
        encoding="utf-8",
    )
    svc = ServiceConfig(service_id="hermes", display_name="Hermes", runtime=RuntimeConfig(unit="hermes.service"), policy=ServicePolicy(report_only=False, restart_enabled=True, kill_enabled=False))
    monkeypatch.setattr("doghouse.security.review.load_services", lambda *_: [svc])
    cfg = DoghouseConfig(paths=PathsConfig(state_dir=str(tmp_path / "state")), host_executor=HostExecutorConfig(enabled=True, policy_path=str(policy_path)))
    report = run_security_review(cfg, persist=True)
    assert report["status"] == "pass"
    assert report["critical_count"] == 0
    assert (tmp_path / "state/security/latest-security-review.json").exists()


def test_restart_drill_blocks_when_active_tasks(monkeypatch, tmp_path):
    svc = ServiceConfig(
        service_id="openclaw",
        display_name="OpenClaw",
        runtime=RuntimeConfig(unit="openclaw.service"),
        policy=ServicePolicy(report_only=False, restart_enabled=True, kill_enabled=False, active_task_guard=True),
    )
    monkeypatch.setattr(restart_mod, "_service_by_id", lambda service_id: svc)
    monkeypatch.setattr(restart_mod, "check_service", lambda service, config, persist=True: type("R", (), {"model_dump": lambda self, mode='json': {"classification": "healthy"}})())
    monkeypatch.setattr(restart_mod, "check_devtasks", lambda *a, **k: {"tasks": [{"classification": "active", "task_id": "x"}], "active_work_sources": []})
    monkeypatch.setattr(restart_mod, "execute_host_action", lambda *a, **k: type("E", (), {"as_dict": lambda self: {"allowed": True, "executed": False}})())
    cfg = DoghouseConfig(paths=PathsConfig(state_dir=str(tmp_path / "state")))
    report = restart_mod.run_restart_drill("openclaw", cfg, execute=True, persist=True)
    assert report["status"] == "blocked"
    assert "active task guard" in " ".join(report["blockers"])


def test_restart_drill_dry_run_pass(monkeypatch, tmp_path):
    svc = ServiceConfig(
        service_id="openclaw",
        display_name="OpenClaw",
        runtime=RuntimeConfig(unit="openclaw.service"),
        policy=ServicePolicy(report_only=False, restart_enabled=True, kill_enabled=False, active_task_guard=True),
    )
    monkeypatch.setattr(restart_mod, "_service_by_id", lambda service_id: svc)
    monkeypatch.setattr(restart_mod, "check_service", lambda service, config, persist=True: type("R", (), {"model_dump": lambda self, mode='json': {"classification": "healthy"}})())
    monkeypatch.setattr(restart_mod, "check_devtasks", lambda *a, **k: {"tasks": [], "active_work_sources": []})
    monkeypatch.setattr(restart_mod, "execute_host_action", lambda *a, **k: type("E", (), {"as_dict": lambda self: {"allowed": True, "executed": False}})())
    cfg = DoghouseConfig(paths=PathsConfig(state_dir=str(tmp_path / "state")))
    report = restart_mod.run_restart_drill("openclaw", cfg, execute=False, persist=True)
    assert report["status"] == "dry_run_pass"
    assert (tmp_path / "state/drills/latest-restart-drill.json").exists()


def test_incident_reconcile_archives_false_open_shadow_reports(monkeypatch, tmp_path):
    incident_dir = tmp_path / "incidents" / "open"
    incident_dir.mkdir(parents=True)
    (incident_dir / "20260512T010101Z-doghouse-shadow-report.json").write_text('{"status":"ok"}\n', encoding="utf-8")
    monkeypatch.setattr(reconcile_mod, "load_services", lambda *_: [])
    monkeypatch.setattr(reconcile_mod, "shadow_once", lambda *a, **k: {"status": "ok"})
    cfg = DoghouseConfig(paths=PathsConfig(state_dir=str(tmp_path / "state"), incident_dir=str(incident_dir)))
    report = reconcile_mod.reconcile_open_incidents(cfg, persist=True)
    assert report["status"] == "ok"
    assert report["actions_count"] == 1
    assert report["remaining_open_count"] == 0
    assert not (incident_dir / "20260512T010101Z-doghouse-shadow-report.json").exists()
    assert (tmp_path / "state/shadow/archive/misfiled-open-incidents/20260512T010101Z-doghouse-shadow-report.json").exists()
