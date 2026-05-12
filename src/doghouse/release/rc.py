from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from doghouse import __version__
from doghouse.audit.checker import run_audit
from doghouse.common.config import DoghouseConfig
from doghouse.evidence.daily import generate_daily_evidence
from doghouse.qa.gate import run_qa_gate
from doghouse.security.review import run_security_review
from doghouse.service_watchdog.state import utc_now_iso, write_state_atomic
from doghouse.soak.report import generate_soak_report


def _git(args: list[str]) -> str:
    try:
        return subprocess.run(['git', *args], cwd='/opt/doghouse', check=False, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception as exc:
        return f'error: {type(exc).__name__}: {exc}'


def build_release_candidate(config: DoghouseConfig, *, persist: bool = True) -> dict[str, Any]:
    qa = run_qa_gate(config, threshold=8.0, persist=True)
    audit = run_audit(config, persist=True)
    security = run_security_review(config, persist=True)
    soak = generate_soak_report(config, since='24h', persist=True)
    evidence = generate_daily_evidence(config, since='24h', threshold=8.0, persist=True)
    git_status = _git(['status', '--short'])
    commit = _git(['rev-parse', '--short', 'HEAD'])
    audit_quality = audit.get('quality') or {}
    checks = {
        'qa_gate_pass': qa.get('status') == 'pass',
        'audit_ok': audit.get('status') == 'ok',
        'security_pass': security.get('status') == 'pass',
        'daily_evidence_pass': evidence.get('status') == 'pass',
        'git_tree_clean_at_start': git_status == '',
    }
    # git_tree_clean_at_start may be false while producing RC docs in a working tree; it is informational, not a blocker.
    blocker_checks = {k: v for k, v in checks.items() if k != 'git_tree_clean_at_start'}
    status = 'rc-ready' if all(blocker_checks.values()) else 'blocked'
    report = {
        'schema': 'doghouse.release_candidate/v1',
        'name': 'Doghouse Watchdog v2 Release Candidate',
        'version': __version__,
        'status': status,
        'created_at': utc_now_iso(),
        'commit': commit,
        'checks': checks,
        'qa': {'status': qa.get('status'), 'score': qa.get('score')},
        'audit': {'status': audit.get('status'), 'quality_score': audit_quality.get('score'), 'critical_count': audit_quality.get('critical_count')},
        'security': {'status': security.get('status'), 'score': security.get('score'), 'critical_count': security.get('critical_count')},
        'soak': {'status': soak.get('status'), 'since': soak.get('since')},
        'evidence': {'status': evidence.get('status')},
        'artifacts': {
            'qa_gate': f'{config.paths.state_dir}/qa/latest-qa-gate.json',
            'daily_evidence_json': f'{config.paths.state_dir}/evidence/latest-daily-evidence.json',
            'security_review': f'{config.paths.state_dir}/security/latest-security-review.json',
            'restart_drill': f'{config.paths.state_dir}/drills/latest-restart-drill.json',
        },
    }
    if persist:
        root = Path(config.paths.state_dir) / 'release'
        root.mkdir(parents=True, exist_ok=True)
        write_state_atomic(root / 'release-candidate.json', report)
        md = [
            '# Doghouse Watchdog v2 Release Candidate',
            '',
            f"Status: {status}",
            f"Version: {__version__}",
            f"Commit: {commit}",
            f"Created: {report['created_at']}",
            '',
            '## Checks',
        ]
        for key, value in checks.items():
            md.append(f'- {key}: {value}')
        md.extend(['', '## Artifact paths'])
        for key, value in report['artifacts'].items():
            md.append(f'- {key}: {value}')
        (root / 'release-candidate.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    return report
