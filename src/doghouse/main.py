from __future__ import annotations

import argparse
import json

import uvicorn

from doghouse.api.app import create_app
from doghouse.audit.checker import run_audit
from doghouse.common.config import load_config_from_env
from doghouse.common.service_config import load_services
from doghouse.devtask_watchdog.checker import check_devtasks, prune_completed_heartbeats, write_heartbeat
from doghouse.notifications.notifier import notification_status, notify_event
from doghouse.host_executor.executor import execute_host_action
from doghouse.evidence.daily import generate_daily_evidence
from doghouse.qa.gate import run_qa_gate
from doghouse.release.rc import build_release_candidate
from doghouse.security.review import run_security_review
from doghouse.shadow.checker import shadow_once
from doghouse.soak.report import generate_soak_report
from doghouse.cutover.manager import cutover_service
from doghouse.service_watchdog.checker import check_service
from doghouse.service_watchdog.reconcile import reconcile_open_incidents
from doghouse.readiness.openclaw import check_openclaw_readiness
from doghouse.drills.restart import run_restart_drill
from doghouse.worker import main as worker_main


def run_check(service_id: str | None) -> int:
    cfg = load_config_from_env()
    services = load_services("/opt/doghouse/config/services.d") or load_services("config/services.d")
    selected = [s for s in services if service_id in (None, s.service_id)]
    if service_id and not selected:
        raise SystemExit(f"unknown service_id: {service_id}")
    for service in selected:
        result = check_service(service, cfg, persist=True)
        print(f"{result.service_id}: {result.classification} - {result.reason}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="doghouse")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve")
    check = sub.add_parser("check-service")
    check.add_argument("service_id", nargs="?")
    devtasks = sub.add_parser("check-devtasks")
    devtasks.add_argument("--active-work-url", default=None)
    heartbeat = sub.add_parser("devtask-heartbeat")
    heartbeat.add_argument("task_id")
    heartbeat.add_argument("--status", default="active")
    heartbeat.add_argument("--progress", default=None)
    heartbeat.add_argument("--pid", type=int, default=None)
    prune_hb = sub.add_parser("prune-devtask-heartbeats")
    prune_hb.add_argument("--max-age-sec", type=int, default=86400)
    sub.add_parser("notification-status")
    notify = sub.add_parser("notify")
    notify.add_argument("--source", default="operator")
    notify.add_argument("--severity", default="warning")
    notify.add_argument("--title", required=True)
    notify.add_argument("--summary", required=True)
    notify.add_argument("--status", default=None)
    notify.add_argument("--force", action="store_true")
    sub.add_parser("audit")
    executor = sub.add_parser("executor")
    executor.add_argument("service_id")
    executor.add_argument("action")
    executor.add_argument("--execute", action="store_true", help="actually run the whitelisted action; default is dry-run")
    executor.add_argument("--reason", default=None, help="operator reason required for destructive execution")
    executor.add_argument("--confirmation-token", default=None, help="required token for destructive execution, e.g. EXECUTE:openclaw:systemctl_restart")
    sub.add_parser("shadow-once")
    sub.add_parser("openclaw-readiness")
    soak = sub.add_parser("soak-report")
    soak.add_argument("--since", default="24h")
    qa = sub.add_parser("qa-gate")
    qa.add_argument("--threshold", type=float, default=8.0)
    evidence = sub.add_parser("daily-evidence")
    evidence.add_argument("--since", default="24h")
    evidence.add_argument("--threshold", type=float, default=8.0)
    drill = sub.add_parser("restart-drill")
    drill.add_argument("service_id")
    drill.add_argument("--execute", action="store_true")
    drill.add_argument("--reason", default=None)
    drill.add_argument("--settle-sec", type=int, default=15)
    sub.add_parser("security-review")
    sub.add_parser("incident-reconcile")
    sub.add_parser("release-candidate")
    cutover = sub.add_parser("cutover-service")
    cutover.add_argument("service_id")
    cutover.add_argument("--execute", action="store_true", help="actually disable the old watchdog timer; default is dry-run")
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--only", default=None)
    worker.add_argument("--dry-run", action="store_true")
    worker.add_argument("--print-schedule", action="store_true")
    args = parser.parse_args()

    if args.command == "check-service":
        return run_check(args.service_id)
    if args.command == "check-devtasks":
        print(json.dumps(check_devtasks(load_config_from_env(), active_work_url=args.active_work_url, persist=True), indent=2, sort_keys=True))
        return 0
    if args.command == "devtask-heartbeat":
        print(json.dumps(write_heartbeat(load_config_from_env(), args.task_id, status=args.status, progress=args.progress, pid=args.pid), indent=2, sort_keys=True))
        return 0
    if args.command == "prune-devtask-heartbeats":
        print(json.dumps(prune_completed_heartbeats(load_config_from_env(), max_age_sec=args.max_age_sec), indent=2, sort_keys=True))
        return 0
    if args.command == "notification-status":
        print(json.dumps(notification_status(load_config_from_env()), indent=2, sort_keys=True))
        return 0
    if args.command == "notify":
        print(json.dumps(notify_event(args.source, args.severity, args.title, args.summary, status=args.status, config=load_config_from_env(), force=args.force), indent=2, sort_keys=True))
        return 0
    if args.command == "audit":
        print(json.dumps(run_audit(load_config_from_env(), persist=True), indent=2, sort_keys=True))
        return 0
    if args.command == "executor":
        services = load_services("/opt/doghouse/config/services.d") or load_services("config/services.d")
        selected = [s for s in services if s.service_id == args.service_id]
        if not selected:
            raise SystemExit(f"unknown service_id: {args.service_id}")
        print(json.dumps(execute_host_action(args.action, selected[0], dry_run=not args.execute, reason=args.reason, confirmation_token=args.confirmation_token).as_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "openclaw-readiness":
        print(json.dumps(check_openclaw_readiness(load_config_from_env(), persist=True), indent=2, sort_keys=True))
        return 0
    if args.command == "shadow-once":
        print(json.dumps(shadow_once(load_config_from_env(), persist=True), indent=2, sort_keys=True))
        return 0
    if args.command == "soak-report":
        print(json.dumps(generate_soak_report(load_config_from_env(), since=args.since, persist=True), indent=2, sort_keys=True))
        return 0
    if args.command == "qa-gate":
        report = run_qa_gate(load_config_from_env(), threshold=args.threshold, persist=True)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("status") == "pass" else 2
    if args.command == "daily-evidence":
        report = generate_daily_evidence(load_config_from_env(), since=args.since, threshold=args.threshold, persist=True)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("status") == "pass" else 2
    if args.command == "restart-drill":
        report = run_restart_drill(args.service_id, load_config_from_env(), execute=args.execute, reason=args.reason, settle_sec=args.settle_sec, persist=True)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("status") in {"pass", "dry_run_pass"} else 2
    if args.command == "security-review":
        report = run_security_review(load_config_from_env(), persist=True)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("status") == "pass" else 2
    if args.command == "incident-reconcile":
        report = reconcile_open_incidents(load_config_from_env(), persist=True)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("status") == "ok" else 2
    if args.command == "release-candidate":
        report = build_release_candidate(load_config_from_env(), persist=True)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("status") == "rc-ready" else 2
    if args.command == "cutover-service":
        print(json.dumps(cutover_service(args.service_id, load_config_from_env(), dry_run=not args.execute), indent=2, sort_keys=True))
        return 0
    if args.command == "worker":
        worker_argv = []
        if args.once:
            worker_argv.append("--once")
        if args.only:
            worker_argv.extend(["--only", args.only])
        if args.dry_run:
            worker_argv.append("--dry-run")
        if args.print_schedule:
            worker_argv.append("--print-schedule")
        return worker_main(worker_argv)

    cfg = load_config_from_env()
    uvicorn.run(create_app(), host=cfg.api.bind, port=cfg.api.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
