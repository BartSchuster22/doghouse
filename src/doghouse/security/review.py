from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from doghouse.common.config import DoghouseConfig
from doghouse.common.service_config import load_services
from doghouse.host_executor.policy import load_executor_policy
from doghouse.service_watchdog.state import utc_now_iso, write_state_atomic


def _mode(path: Path) -> str | None:
    try:
        return oct(path.stat().st_mode & 0o777)
    except OSError:
        return None


def run_security_review(config: DoghouseConfig, *, persist: bool = True) -> dict[str, Any]:
    policy = load_executor_policy(config.host_executor.policy_path)
    services = load_services('/opt/doghouse/config/services.d') or load_services('config/services.d')
    findings: list[dict[str, Any]] = []

    def add(check: str, status: str, detail: str, severity: str = 'info') -> None:
        findings.append({'check': check, 'status': status, 'severity': severity, 'detail': detail})

    if policy.enabled:
        add('executor_enabled', 'pass', 'host executor is explicitly enabled')
    else:
        add('executor_enabled', 'fail', 'host executor disabled', 'critical')
    add('allowed_binaries', 'pass' if set(policy.allowed_binaries) <= {'/bin/systemctl', '/usr/bin/systemctl'} else 'fail', ', '.join(policy.allowed_binaries), 'critical' if not set(policy.allowed_binaries) <= {'/bin/systemctl', '/usr/bin/systemctl'} else 'info')
    add('absolute_argv0', 'pass' if policy.require_absolute_argv0 else 'fail', str(policy.require_absolute_argv0), 'critical' if not policy.require_absolute_argv0 else 'info')
    add('shell_free_design', 'pass', 'executor uses subprocess.run(..., shell=False) in implementation')
    add('destructive_reason', 'pass' if policy.require_reason_for_destructive and policy.min_destructive_reason_chars >= 12 else 'fail', f'required={policy.require_reason_for_destructive} min={policy.min_destructive_reason_chars}', 'critical' if not policy.require_reason_for_destructive else 'info')
    add('destructive_confirmation', 'pass' if policy.require_confirmation_token_for_destructive else 'fail', str(policy.require_confirmation_token_for_destructive), 'critical' if not policy.require_confirmation_token_for_destructive else 'info')
    add('audit_hash_chain', 'pass' if policy.audit_include_hash_chain else 'warn', str(policy.audit_include_hash_chain), 'warning' if not policy.audit_include_hash_chain else 'info')
    add('restart_cooldown', 'pass' if policy.restart_cooldown_sec >= 300 else 'warn', f'{policy.restart_cooldown_sec}s', 'warning' if policy.restart_cooldown_sec < 300 else 'info')
    add('allowed_services_minimal', 'pass' if set(policy.allowed_services) <= {'hermes', 'openclaw'} else 'warn', ', '.join(sorted(policy.allowed_services)), 'warning')

    for svc in services:
        add(f'{svc.service_id}.kill_disabled', 'pass' if not svc.policy.kill_enabled else 'fail', f'kill_enabled={svc.policy.kill_enabled}', 'critical' if svc.policy.kill_enabled else 'info')
        add(f'{svc.service_id}.active_task_guard', 'pass' if svc.policy.active_task_guard else 'warn', f'active_task_guard={svc.policy.active_task_guard}', 'warning')
        if svc.policy.restart_enabled:
            add(f'{svc.service_id}.restart_policy', 'pass' if not svc.policy.report_only else 'fail', f'restart_enabled={svc.policy.restart_enabled} report_only={svc.policy.report_only}', 'critical' if svc.policy.report_only else 'info')

    sensitive = [Path(config.host_executor.policy_path), Path('/etc/systemd/system/doghouse-check@.service')]
    for path in sensitive:
        mode = _mode(path)
        add(f'file_mode:{path}', 'pass' if mode and int(mode, 8) & 0o002 == 0 else 'warn', f'mode={mode}', 'warning')

    critical = sum(1 for f in findings if f['status'] == 'fail' and f['severity'] == 'critical')
    warnings = sum(1 for f in findings if f['status'] == 'warn' or f['severity'] == 'warning' and f['status'] != 'pass')
    status = 'pass' if critical == 0 else 'fail'
    score = max(0.0, 10.0 - critical * 2.5 - warnings * 0.5)
    report = {
        'schema': 'doghouse.security_review/v1',
        'status': status,
        'score': round(score, 1),
        'critical_count': critical,
        'warning_count': warnings,
        'checked_at': utc_now_iso(),
        'findings': findings,
        'scope': ['host_executor', 'service_policies', 'systemd_units', 'filesystem_modes'],
    }
    if persist:
        root = Path(config.paths.state_dir) / 'security'
        root.mkdir(parents=True, exist_ok=True)
        write_state_atomic(root / 'latest-security-review.json', report)
    return report
