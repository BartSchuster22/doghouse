from __future__ import annotations

import argparse
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from doghouse.audit.checker import run_audit
from doghouse.common.config import DoghouseConfig, load_config_from_env
from doghouse.common.service_config import load_services
from doghouse.devtask_watchdog.checker import check_devtasks
from doghouse.evidence.daily import generate_daily_evidence
from doghouse.notifications.notifier import notification_status, notify_event, notify_from_audit
from doghouse.readiness.openclaw import check_openclaw_readiness
from doghouse.service_watchdog.checker import check_service
from doghouse.service_watchdog.reconcile import reconcile_open_incidents
from doghouse.shadow.checker import shadow_once


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    interval_sec: int
    run: Callable[[DoghouseConfig], dict[str, Any]]
    description: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_interval(value: int, minimum: int = 1) -> int:
    return max(minimum, int(value))


def _lock_dir(config: DoghouseConfig) -> Path:
    return Path(config.paths.state_dir) / "worker-locks"


@contextmanager
def job_lock(config: DoghouseConfig, job_name: str) -> Iterator[bool]:
    """Acquire a per-job lock using atomic file creation.

    The worker is single-threaded, but these locks prevent overlap across two worker
    processes or a manually invoked `doghouse worker --once` while the containerized
    worker is running. Stale lock breaking is intentionally conservative: operators
    can remove a lock after checking the recorded pid/created_at.
    """
    lock_path = _lock_dir(config) / f"{job_name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pid": os.getpid(), "job": job_name, "created_at": utc_now_iso()}
    fd: int | None = None
    acquired = False
    try:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fd = None
                fh.write(json.dumps(payload, sort_keys=True) + "\n")
            acquired = True
        except FileExistsError:
            acquired = False
        yield acquired
    finally:
        if fd is not None:
            os.close(fd)
        if acquired:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def _shadow_report_only_service(service):
    """Return a worker-safe service config that cannot execute restarts.

    The canonical service configs may intentionally allow host-side restart
    execution for the existing host watchdog path. The containerized worker is
    only approved for shadow/report-only scheduling, so it must force service
    checks into report-only mode before calling the shared checker.
    """
    return service.model_copy(
        deep=True,
        update={
            "policy": service.policy.model_copy(
                update={"report_only": True, "restart_enabled": False, "kill_enabled": False}
            )
        },
    )


def _run_service_checks(config: DoghouseConfig) -> dict[str, Any]:
    services = load_services("/opt/doghouse/config/services.d") or load_services("config/services.d")
    results = []
    for service in services:
        result = check_service(_shadow_report_only_service(service), config, persist=True)
        results.append(result.model_dump())
    return {"status": "ok", "service_count": len(results), "results": results}


def _run_devtasks(config: DoghouseConfig) -> dict[str, Any]:
    return check_devtasks(config, active_work_url=None, persist=True)


def _run_audit_with_notification(config: DoghouseConfig) -> dict[str, Any]:
    audit = run_audit(config, persist=True)
    notification = notify_from_audit(audit, config=config, force=False)
    return {"status": audit.get("status", "unknown"), "audit": audit, "notification": notification}


def _run_notification_status(config: DoghouseConfig) -> dict[str, Any]:
    return notification_status(config)


def _run_notification_sweep(config: DoghouseConfig) -> dict[str, Any]:
    return notify_event(
        "notification_sweep",
        "info",
        "Doghouse notification sweep",
        "Notification layer sweep completed",
        status="ok",
        config=config,
        force=False,
    )


def _run_shadow(config: DoghouseConfig) -> dict[str, Any]:
    return shadow_once(config, persist=True)


def next_daily_evidence_delay_sec(config: DoghouseConfig, *, now_utc_seconds: int | None = None) -> int:
    scheduler = config.scheduler
    target = (_safe_interval(scheduler.daily_evidence_utc_hour, minimum=0) % 24) * 3600
    target += (_safe_interval(scheduler.daily_evidence_utc_minute, minimum=0) % 60) * 60
    if now_utc_seconds is None:
        now = datetime.now(timezone.utc)
        now_utc_seconds = now.hour * 3600 + now.minute * 60 + now.second
    delay = target - int(now_utc_seconds)
    if delay <= 0:
        delay += 24 * 3600
    return delay


def _run_daily_evidence(config: DoghouseConfig) -> dict[str, Any]:
    return generate_daily_evidence(config, since="24h", threshold=8.0, persist=True)


def _run_incident_reconcile(config: DoghouseConfig) -> dict[str, Any]:
    return reconcile_open_incidents(config, persist=True)


def _run_openclaw_readiness(config: DoghouseConfig) -> dict[str, Any]:
    return check_openclaw_readiness(config, persist=True, report_only=True)


def build_jobs(config: DoghouseConfig) -> list[ScheduledJob]:
    scheduler = config.scheduler
    service_interval = _safe_interval(getattr(scheduler, "service_interval_sec", 60))
    devtask_interval = _safe_interval(getattr(scheduler, "devtask_interval_sec", 60))
    audit_interval = _safe_interval(getattr(scheduler, "audit_interval_sec", 300))
    notification_interval = _safe_interval(getattr(scheduler, "notification_interval_sec", 300))
    notification_sweep_interval = _safe_interval(getattr(scheduler, "notification_sweep_interval_sec", 900))
    shadow_interval = _safe_interval(getattr(scheduler, "shadow_interval_sec", 300))
    incident_interval = _safe_interval(getattr(scheduler, "incident_reconcile_interval_sec", 300))
    openclaw_interval = _safe_interval(getattr(scheduler, "openclaw_readiness_interval_sec", 300))
    daily_interval = _safe_interval(getattr(scheduler, "daily_evidence_interval_sec", 86400))
    return [
        ScheduledJob("service-checks", service_interval, _run_service_checks, "doghouse check-service for every configured service"),
        ScheduledJob("devtasks", devtask_interval, _run_devtasks, "doghouse check-devtasks"),
        ScheduledJob("audit", audit_interval, _run_audit_with_notification, "doghouse audit plus local-outbox notification dedupe"),
        ScheduledJob("notification-status", notification_interval, _run_notification_status, "doghouse notification-status"),
        ScheduledJob("notification-sweep", notification_sweep_interval, _run_notification_sweep, "doghouse notification sweep through local-outbox dedupe"),
        ScheduledJob("shadow-once", shadow_interval, _run_shadow, "doghouse shadow-once"),
        ScheduledJob("daily-evidence", daily_interval, _run_daily_evidence, "doghouse daily-evidence --since 24h --threshold 8.0"),
        ScheduledJob("incident-reconcile", incident_interval, _run_incident_reconcile, "doghouse incident-reconcile"),
        ScheduledJob("openclaw-readiness", openclaw_interval, _run_openclaw_readiness, "doghouse openclaw-readiness"),
    ]


def describe_schedule(config: DoghouseConfig) -> dict[str, Any]:
    return {
        "schema": "doghouse.worker.schedule/v1",
        "mode": "shadow-report-only",
        "restart_actions": "not scheduled; worker service-checks and openclaw-readiness force report_only=true and restart_enabled=false before shared checker execution; worker never passes --execute and does not call executor/restart-drill/cutover-service",
        "overlap_prevention": "single-process scheduler loop plus atomic per-job lock files under state_dir/worker-locks",
        "jobs": [
            {
                "name": job.name,
                "interval_sec": job.interval_sec,
                "description": job.description,
                **({"run_at_utc": f"{config.scheduler.daily_evidence_utc_hour:02d}:{config.scheduler.daily_evidence_utc_minute:02d}"} if job.name == "daily-evidence" else {}),
            }
            for job in build_jobs(config)
        ],
    }


def run_job(config: DoghouseConfig, job: ScheduledJob, dry_run: bool = False) -> dict[str, Any]:
    started_at = utc_now_iso()
    if dry_run:
        return {"job": job.name, "status": "dry_run", "started_at": started_at, "description": job.description}
    with job_lock(config, job.name) as acquired:
        if not acquired:
            return {"job": job.name, "status": "skipped_locked", "started_at": started_at}
        try:
            result = job.run(config)
            return {"job": job.name, "status": "ok", "started_at": started_at, "finished_at": utc_now_iso(), "result": result}
        except Exception as exc:  # pragma: no cover - exercised by operational smoke more than unit tests
            return {"job": job.name, "status": "error", "started_at": started_at, "finished_at": utc_now_iso(), "error": str(exc), "error_type": type(exc).__name__}


def run_once(config: DoghouseConfig, *, only: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    jobs = build_jobs(config)
    if only:
        jobs = [job for job in jobs if job.name == only]
        if not jobs:
            raise SystemExit(f"unknown worker job: {only}")
    return {
        "schema": "doghouse.worker.run/v1",
        "mode": "shadow-report-only",
        "started_at": utc_now_iso(),
        "dry_run": dry_run,
        "jobs": [run_job(config, job, dry_run=dry_run) for job in jobs],
        "restart_actions": "report-only; no restart execution path invoked",
    }


def run_forever(config: DoghouseConfig, *, dry_run: bool = False) -> int:
    jobs = build_jobs(config)
    next_run = {job.name: 0.0 for job in jobs}
    while True:
        now = time.monotonic()
        sleep_for = 1.0
        for job in jobs:
            if now >= next_run[job.name]:
                print(json.dumps(run_job(config, job, dry_run=dry_run), sort_keys=True), flush=True)
                next_run[job.name] = time.monotonic() + job.interval_sec
            sleep_for = min(sleep_for, max(0.1, next_run[job.name] - time.monotonic()))
        time.sleep(sleep_for)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="doghouse-worker")
    parser.add_argument("--once", action="store_true", help="run due shadow/report-only jobs once, then exit")
    parser.add_argument("--only", choices=[job.name for job in build_jobs(load_config_from_env())], default=None, help="run only one job with --once")
    parser.add_argument("--dry-run", action="store_true", help="describe/run the scheduler without invoking job side effects")
    parser.add_argument("--print-schedule", action="store_true", help="print the configured schedule and exit")
    args = parser.parse_args(argv)

    config = load_config_from_env()
    if args.print_schedule:
        print(json.dumps(describe_schedule(config), indent=2, sort_keys=True))
        return 0
    if args.once:
        print(json.dumps(run_once(config, only=args.only, dry_run=args.dry_run), indent=2, sort_keys=True))
        return 0
    return run_forever(config, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
