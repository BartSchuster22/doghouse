from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from doghouse.audit.checker import run_audit
from doghouse.common.config import DoghouseConfig
from doghouse.common.service_config import load_services
from doghouse.service_watchdog.checker import check_service
from doghouse.service_watchdog.state import utc_now_iso
from doghouse.shadow.checker import shadow_once
from doghouse.soak.report import generate_soak_report


def _score_item(name: str, ok: bool, weight: float, detail: Any = None) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "weight": weight, "earned": weight if ok else 0.0, "detail": detail}


def run_qa_gate(config: DoghouseConfig, threshold: float = 8.0, persist: bool = True) -> dict[str, Any]:
    services = load_services("/opt/doghouse/config/services.d") or load_services("config/services.d")
    service_results = [check_service(service, config, persist=True).model_dump(mode="json") for service in services]
    audit = run_audit(config, persist=True)
    shadow = shadow_once(config, persist=True)
    soak = generate_soak_report(config, since="24h", persist=True)

    service_ok = bool(service_results) and all(item.get("classification") == "healthy" for item in service_results)
    no_kill = all(item.get("kill_enabled") is False for item in service_results)
    no_recent_restart = not soak.get("restart_actions")
    audit_ok = audit.get("status") == "ok"
    shadow_ok = shadow.get("status") == "ok"
    scheduler_ok = (audit.get("sections") or {}).get("scheduler_freshness", {}).get("status") == "ok"
    paths_ok = (audit.get("sections") or {}).get("paths", {}).get("status") == "ok"
    executor_ok = (audit.get("sections") or {}).get("executor_policy", {}).get("status") == "ok"
    devtask_ok = (audit.get("sections") or {}).get("devtask_state", {}).get("status") == "ok"
    incidents_ok = (soak.get("incidents") or {}).get("count", 0) == 0

    checks = [
        _score_item("registered_services_healthy", service_ok, 1.5, [{"service_id": r.get("service_id"), "classification": r.get("classification")} for r in service_results]),
        _score_item("audit_ok", audit_ok, 1.25, audit.get("status")),
        _score_item("shadow_ok", shadow_ok, 1.0, shadow.get("status")),
        _score_item("scheduler_freshness_ok", scheduler_ok, 1.0),
        _score_item("paths_writable_ok", paths_ok, 0.75),
        _score_item("executor_policy_hardened_ok", executor_ok, 1.0),
        _score_item("devtask_state_ok", devtask_ok, 0.75),
        _score_item("kill_disabled_everywhere", no_kill, 0.75),
        _score_item("no_restart_actions_in_soak_window", no_recent_restart, 1.0, soak.get("restart_actions")),
        _score_item("no_incidents_in_soak_window", incidents_ok, 1.0, (soak.get("incidents") or {}).get("count", 0)),
    ]
    score = round(sum(item["earned"] for item in checks), 2)
    max_score = round(sum(item["weight"] for item in checks), 2)
    normalized_score = round((score / max_score) * 10, 2) if max_score else 0.0
    passed = normalized_score >= threshold
    report = {
        "generated_at": utc_now_iso(),
        "status": "pass" if passed else "fail",
        "threshold": threshold,
        "score": normalized_score,
        "raw_score": score,
        "max_score": max_score,
        "checks": checks,
        "service_count": len(service_results),
        "service_results": service_results,
        "audit_status": audit.get("status"),
        "shadow_status": shadow.get("status"),
        "soak_status": soak.get("status"),
    }
    if persist:
        out = Path(config.paths.state_dir) / "qa" / "latest-qa-gate.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(out)
        report["path"] = str(out)
    return report
