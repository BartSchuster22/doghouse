from __future__ import annotations

import argparse

import uvicorn

from doghouse.api.app import create_app
from doghouse.common.config import load_config_from_env
from doghouse.common.service_config import load_services
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
    args = parser.parse_args()

    if args.command == "check-service":
        return run_check(args.service_id)

    cfg = load_config_from_env()
    uvicorn.run(create_app(), host=cfg.api.bind, port=cfg.api.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
