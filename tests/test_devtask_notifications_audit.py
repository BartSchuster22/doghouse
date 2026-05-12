from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from doghouse.audit.checker import summarize_audit_quality
from doghouse.common.config import DoghouseConfig, NotificationConfig, PathsConfig
from doghouse.devtask_watchdog.checker import check_devtasks, classify_task, read_heartbeats, write_heartbeat
from doghouse.notifications.notifier import notification_status, notify_event


def test_devtask_heartbeat_write_and_check(tmp_path):
    cfg = DoghouseConfig(paths=PathsConfig(state_dir=str(tmp_path / "state"), checkpoint_dir=str(tmp_path / "checkpoints"), incident_dir=str(tmp_path / "incidents"), log_dir=str(tmp_path / "logs")))
    hb = write_heartbeat(cfg, "task-1", progress="testing")
    assert hb["task_id"] == "task-1"
    assert hb["schema"] == "doghouse.devtask.heartbeat/v1"
    assert read_heartbeats(cfg)[0]["heartbeat_hash"]
    result = check_devtasks(cfg, active_work_url=None, persist=True)
    assert result["task_count"] == 1
    assert result["status"] == "ok"


def test_devtask_expected_progress_becomes_stuck():
    now = datetime.now(timezone.utc)
    task = {
        "task_id": "stuck-task",
        "status": "active",
        "last_seen_at": now.isoformat(),
        "expected_progress_at": (now - timedelta(seconds=1)).isoformat(),
    }
    classification, reason = classify_task(task, now=now)
    assert classification == "stuck"
    assert "expected progress" in reason


def test_notification_outbox_and_dedupe(tmp_path):
    cfg = DoghouseConfig(
        notifications=NotificationConfig(
            enabled=True,
            min_severity="warning",
            outbox_path=str(tmp_path / "outbox.jsonl"),
            latest_path=str(tmp_path / "latest.json"),
        )
    )
    first = notify_event("test", "warning", "Title", "Summary", config=cfg)
    second = notify_event("test", "warning", "Title", "Summary", config=cfg)
    assert first["accepted"] is True
    assert second["accepted"] is False
    assert second["deduped"] is True
    assert notification_status(cfg)["outbox_events"] == 1


def test_audit_quality_summary_counts_issues():
    quality = summarize_audit_quality({
        "ok_section": {"status": "ok"},
        "bad_section": {"status": "attention", "issues": [{"severity": "critical", "reason": "bad"}]},
    })
    assert quality["status"] == "attention"
    assert quality["critical_count"] == 1
    assert quality["score"] < 8
