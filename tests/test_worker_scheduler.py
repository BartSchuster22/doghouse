from __future__ import annotations

import json
from pathlib import Path

from doghouse.common.config import DoghouseConfig, PathsConfig, SchedulerConfig
from doghouse.common.service_config import ServiceConfig
from doghouse.service_watchdog.state import EndpointCheckResult
from doghouse.worker import (
    ScheduledJob,
    _run_notification_sweep,
    _run_openclaw_readiness,
    _run_service_checks,
    describe_schedule,
    job_lock,
    next_daily_evidence_delay_sec,
    run_job,
    run_once,
)


def config(tmp_path: Path) -> DoghouseConfig:
    return DoghouseConfig(
        paths=PathsConfig(
            state_dir=str(tmp_path / "state"),
            checkpoint_dir=str(tmp_path / "checkpoints"),
            incident_dir=str(tmp_path / "incidents"),
            log_dir=str(tmp_path / "logs"),
        ),
        scheduler=SchedulerConfig(
            service_interval_sec=11,
            devtask_interval_sec=12,
            audit_interval_sec=13,
            notification_interval_sec=14,
            notification_sweep_interval_sec=19,
            shadow_interval_sec=15,
            incident_reconcile_interval_sec=16,
            openclaw_readiness_interval_sec=17,
            daily_evidence_interval_sec=18,
            daily_evidence_utc_hour=6,
            daily_evidence_utc_minute=10,
        ),
    )


def test_worker_schedule_documents_all_shadow_jobs(tmp_path):
    schedule = describe_schedule(config(tmp_path))
    jobs = {job["name"]: job["interval_sec"] for job in schedule["jobs"]}
    assert jobs == {
        "service-checks": 11,
        "devtasks": 12,
        "audit": 13,
        "notification-status": 14,
        "notification-sweep": 19,
        "shadow-once": 15,
        "daily-evidence": 18,
        "incident-reconcile": 16,
        "openclaw-readiness": 17,
    }
    daily = next(job for job in schedule["jobs"] if job["name"] == "daily-evidence")
    assert daily["run_at_utc"] == "06:10"
    assert "restart" in schedule["restart_actions"]
    assert "not scheduled" in schedule["restart_actions"]


def test_run_once_dry_run_has_no_side_effect_job_execution(tmp_path):
    report = run_once(config(tmp_path), dry_run=True)
    assert report["mode"] == "shadow-report-only"
    assert {job["status"] for job in report["jobs"]} == {"dry_run"}
    assert not (tmp_path / "state" / "worker-locks").exists()


def test_per_job_lock_skips_overlapping_run(tmp_path):
    cfg = config(tmp_path)
    called = False

    def should_not_run(_cfg):
        nonlocal called
        called = True
        return {"status": "bad"}

    job = ScheduledJob("audit", 60, should_not_run, "test")
    with job_lock(cfg, "audit") as acquired:
        assert acquired is True
        report = run_job(cfg, job)
    assert report["status"] == "skipped_locked"
    assert called is False


def test_run_job_releases_lock_after_success(tmp_path):
    cfg = config(tmp_path)
    job = ScheduledJob("devtasks", 60, lambda _cfg: {"status": "ok"}, "test")
    report = run_job(cfg, job)
    assert report["status"] == "ok"
    assert report["result"] == {"status": "ok"}
    assert not (Path(cfg.paths.state_dir) / "worker-locks" / "devtasks.lock").exists()


def test_worker_service_checks_force_shadow_report_only_policy(tmp_path, monkeypatch):
    risky_service = ServiceConfig.model_validate({
        "service_id": "openclaw",
        "display_name": "OpenClaw Gateway",
        "endpoints": {"live": "http://127.0.0.1:18789/live"},
        "policy": {
            "report_only": False,
            "restart_enabled": True,
            "kill_enabled": False,
            "failure_threshold": 3,
        },
    })
    seen_policies = []

    monkeypatch.setattr("doghouse.worker.load_services", lambda _path: [risky_service])

    def fake_check_service(service, _config, persist=True):
        seen_policies.append((service.policy.report_only, service.policy.restart_enabled, persist))

        class Result:
            def model_dump(self):
                return {"service_id": service.service_id, "action": None}

        return Result()

    monkeypatch.setattr("doghouse.worker.check_service", fake_check_service)

    report = _run_service_checks(config(tmp_path))

    assert report["status"] == "ok"
    assert seen_policies == [(True, False, True)]
    assert risky_service.policy.report_only is False
    assert risky_service.policy.restart_enabled is True


def test_worker_service_checks_do_not_execute_restart_when_threshold_met(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    state_path = Path(cfg.paths.state_dir) / "services" / "openclaw.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"consecutive_liveness_failures": 2}), encoding="utf-8")
    risky_service = ServiceConfig.model_validate({
        "service_id": "openclaw",
        "display_name": "OpenClaw Gateway",
        "endpoints": {"live": "http://127.0.0.1:18789/live"},
        "policy": {
            "report_only": False,
            "restart_enabled": True,
            "kill_enabled": False,
            "failure_threshold": 3,
            "active_task_guard": False,
        },
    })

    monkeypatch.setattr("doghouse.worker.load_services", lambda _path: [risky_service])
    monkeypatch.setattr(
        "doghouse.service_watchdog.checker.check_endpoint",
        lambda name, url, timeout_sec: EndpointCheckResult(
            name=name,
            url=url,
            ok=False,
            error="forced failure",
            checked_at="2026-01-01T00:00:00Z",
        ),
    )

    def forbidden_execute(*_args, **_kwargs):
        raise AssertionError("worker service-checks must not execute host restart actions")

    monkeypatch.setattr("doghouse.service_watchdog.checker.execute_host_action", forbidden_execute)

    report = _run_service_checks(cfg)

    result = report["results"][0]
    assert result["classification"] == "liveness_failed_threshold_met"
    assert result["report_only"] is True
    assert result["restart_enabled"] is False
    assert result["action"] == {
        "action": "systemctl_restart",
        "executed": False,
        "reason": "report-only or restart disabled",
    }


def test_notification_sweep_preserves_existing_dedupe_semantics(tmp_path, monkeypatch):
    calls = []

    def fake_notify_event(*args, **kwargs):
        calls.append((args, kwargs))
        return {"accepted": False, "reason": "severity below min_severity warning"}

    monkeypatch.setattr("doghouse.worker.notify_event", fake_notify_event)

    report = _run_notification_sweep(config(tmp_path))

    assert report == {"accepted": False, "reason": "severity below min_severity warning"}
    assert calls == [
        (
            ("notification_sweep", "info", "Doghouse notification sweep", "Notification layer sweep completed"),
            {"status": "ok", "config": config(tmp_path), "force": False},
        )
    ]


def test_daily_evidence_initial_delay_targets_next_off_peak_utc(tmp_path):
    cfg = config(tmp_path)

    before_window = 6 * 3600 + 9 * 60
    after_window = 6 * 3600 + 11 * 60

    assert next_daily_evidence_delay_sec(cfg, now_utc_seconds=before_window) == 60
    assert next_daily_evidence_delay_sec(cfg, now_utc_seconds=after_window) == (24 * 3600) - 60


def test_worker_openclaw_readiness_does_not_execute_restart_when_threshold_met(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    state_path = Path(cfg.paths.state_dir) / "services" / "openclaw.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"consecutive_liveness_failures": 2}), encoding="utf-8")
    risky_service = ServiceConfig.model_validate({
        "service_id": "openclaw",
        "display_name": "OpenClaw Gateway",
        "runtime": {"unit": "openclaw.service"},
        "endpoints": {
            "live": "http://127.0.0.1:18789/live",
            "ready": "http://127.0.0.1:18789/ready",
            "health": "http://127.0.0.1:18789/health",
        },
        "policy": {
            "report_only": False,
            "restart_enabled": True,
            "kill_enabled": False,
            "failure_threshold": 3,
            "active_task_guard": False,
        },
    })

    monkeypatch.setattr("doghouse.readiness.openclaw.load_services", lambda _path: [risky_service])
    monkeypatch.setattr("doghouse.readiness.openclaw._systemctl_is_active", lambda unit: {"unit": unit, "active": False})
    monkeypatch.setattr(
        "doghouse.service_watchdog.checker.check_endpoint",
        lambda name, url, timeout_sec: EndpointCheckResult(
            name=name,
            url=url,
            ok=False,
            error="forced failure",
            checked_at="2026-01-01T00:00:00Z",
        ),
    )
    monkeypatch.setattr(
        "doghouse.readiness.openclaw.check_endpoint",
        lambda name, url, timeout_sec: EndpointCheckResult(
            name=name,
            url=url,
            ok=False,
            error="forced failure",
            checked_at="2026-01-01T00:00:00Z",
        ),
    )

    def forbidden_execute(*_args, **_kwargs):
        raise AssertionError("worker openclaw-readiness must not execute host restart actions")

    monkeypatch.setattr("doghouse.service_watchdog.checker.execute_host_action", forbidden_execute)

    report = _run_openclaw_readiness(cfg)

    service_check = report["service_check"]
    assert service_check["classification"] == "liveness_failed_threshold_met"
    assert service_check["report_only"] is True
    assert service_check["restart_enabled"] is False
    assert service_check["action"] == {
        "action": "systemctl_restart",
        "executed": False,
        "reason": "report-only or restart disabled",
    }
    assert risky_service.policy.report_only is False
    assert risky_service.policy.restart_enabled is True
