from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from doghouse.audit.checker import run_audit
from doghouse.common.config import DoghouseConfig
from doghouse.qa.gate import run_qa_gate
from doghouse.service_watchdog.state import utc_now_iso
from doghouse.shadow.checker import shadow_once
from doghouse.soak.report import generate_soak_report


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    qa = report.get("qa", {})
    soak = report.get("soak", {})
    audit = report.get("audit", {})
    shadow = report.get("shadow", {})
    lines = [
        "# Doghouse Daily Evidence",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Overall status: {report.get('status')}",
        "",
        "## QA Gate",
        f"Status: {qa.get('status')}",
        f"Score: {qa.get('score')}/10",
        f"Threshold: {qa.get('threshold')}",
        "",
        "## Soak",
        f"Status: {soak.get('status')}",
        f"Attention: {', '.join(soak.get('attention') or []) if soak.get('attention') else 'none'}",
        f"Incidents: {(soak.get('incidents') or {}).get('count')}",
        f"Restart actions: {len(soak.get('restart_actions') or [])}",
        "",
        "## Audit",
        f"Status: {audit.get('status')}",
        "",
        "## Shadow",
        f"Status: {shadow.get('status')}",
        "",
        "## Service State",
    ]
    for sid, state in (soak.get("latest_states") or {}).items():
        lines.append(f"- {sid}: {state.get('classification')}")
    lines.extend(["", "## QA Checks"])
    for item in qa.get("checks") or []:
        lines.append(f"- [{'x' if item.get('ok') else ' '}] {item.get('name')} ({item.get('earned')}/{item.get('weight')})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_daily_evidence(config: DoghouseConfig, since: str = "24h", threshold: float = 8.0, persist: bool = True) -> dict[str, Any]:
    qa = run_qa_gate(config, threshold=threshold, persist=True)
    soak = generate_soak_report(config, since=since, persist=True)
    audit = run_audit(config, persist=True)
    shadow = shadow_once(config, persist=True)
    status = "pass" if qa.get("status") == "pass" and audit.get("status") == "ok" and shadow.get("status") == "ok" else "attention"
    report = {
        "generated_at": utc_now_iso(),
        "status": status,
        "since": since,
        "qa": qa,
        "soak": soak,
        "audit": audit,
        "shadow": shadow,
    }
    if persist:
        root = Path(config.paths.state_dir) / "evidence"
        root.mkdir(parents=True, exist_ok=True)
        json_path = root / "latest-daily-evidence.json"
        md_path = root / "latest-daily-evidence.md"
        tmp = json_path.with_suffix(json_path.suffix + ".tmp")
        tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(json_path)
        _write_markdown(md_path, report)
        report["path"] = str(json_path)
        report["markdown_path"] = str(md_path)
    return report
