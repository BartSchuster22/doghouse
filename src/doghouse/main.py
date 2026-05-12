from __future__ import annotations

import argparse
import json

import uvicorn

from doghouse.api.app import create_app
from doghouse.audit.checker import run_audit
from doghouse.common.config import load_config_from_env
from doghouse.common.service_config import load_services
from doghouse.devtask_watchdog.checker import check_devtasks
from doghouse.host_executor.executor import execute_host_action
from doghouse.evidence.daily import generate_daily_evidence
from doghouse.qa.gate import run_qa_gate
from doghouse.shadow.checker import shadow_once
from doghouse.soak.report import generate_soak_report
from doghouse.cutover.manager import cutover_service
from doghouse.service_watchdog.checker import check_service


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
    sub.add_parser("audit")
    executor = sub.add_parser("executor")
    executor.add_argument("service_id")
    executor.add_argument("action")
    executor.add_argument("--execute", action="store_true", help="actually run the whitelisted action; default is dry-run")
    sub.add_parser("shadow-once")
    soak = sub.add_parser("soak-report")
    soak.add_argument("--since", default="24h")
    qa = sub.add_parser("qa-gate")
    qa.add_argument("--threshold", type=float, default=8.0)
    evidence = sub.add_parser("daily-evidence")
    evidence.add_argument("--since", default="24h")
    evidence.add_argument("--threshold", type=float, default=8.0)
    cutover = sub.add_parser("cutover-service")
    cutover.add_argument("service_id")
    cutover.add_argument("--execute", action="store_true", help="actually disable the old watchdog timer; default is dry-run")
    args = parser.parse_args()

    if args.command == "check-service":
        return run_check(args.service_id)
    if args.command == "check-devtasks":
        print(json.dumps(check_devtasks(load_config_from_env(), active_work_url=args.active_work_url, persist=True), indent=2, sort_keys=True))
        return 0
    if args.command == "audit":
        print(json.dumps(run_audit(load_config_from_env(), persist=True), indent=2, sort_keys=True))
        return 0
    if args.command == "executor":
        services = load_services("/opt/doghouse/config/services.d") or load_services("config/services.d")
        selected = [s for s in services if s.service_id == args.service_id]
        if not selected:
            raise SystemExit(f"unknown service_id: {args.service_id}")
        print(json.dumps(execute_host_action(args.action, selected[0], dry_run=not args.execute).as_dict(), indent=2, sort_keys=True))
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
    if args.command == "cutover-service":
        print(json.dumps(cutover_service(args.service_id, load_config_from_env(), dry_run=not args.execute), indent=2, sort_keys=True))
        return 0

    cfg = load_config_from_env()
    uvicorn.run(create_app(), host=cfg.api.bind, port=cfg.api.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
