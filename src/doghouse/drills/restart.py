from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from doghouse.common.config import DoghouseConfig
from doghouse.common.service_config import load_services
from doghouse.devtask_watchdog.checker import check_devtasks
from doghouse.host_executor.executor import destructive_confirmation_token, execute_host_action
from doghouse.service_watchdog.checker import check_service
from doghouse.service_watchdog.state import utc_now_iso, write_state_atomic


def _service_by_id(service_id: str):
    services = load_services('/opt/doghouse/config/services.d') or load_services('config/services.d')
    for svc in services:
        if svc.service_id == service_id:
            return svc
    raise ValueError(f'unknown service_id: {service_id}')


def _safe_active_tasks(config: DoghouseConfig, service) -> dict[str, Any]:
    active_work_url = service.endpoints.get('active_work') or service.endpoints.get('watchdog_active_work') or ''
    result = check_devtasks(config, active_work_url=active_work_url, persist=True)
    active = [t for t in result.get('tasks', []) if t.get('classification') in {'active', 'idle', 'stuck', 'orphaned', 'unknown'}]
    source_failures = [s for s in result.get('active_work_sources', []) if s.get('ok') is False and s.get('url')]
    return {'result': result, 'active': active, 'source_failures': source_failures}


def run_restart_drill(service_id: str, config: DoghouseConfig, *, execute: bool = False, reason: str | None = None, settle_sec: int = 15, persist: bool = True) -> dict[str, Any]:
    service = _service_by_id(service_id)
    reason = reason or f'Controlled Doghouse restart drill for {service_id}'
    started_at = utc_now_iso()
    before = check_service(service, config, persist=True).model_dump(mode='json')
    active = _safe_active_tasks(config, service)
    blockers: list[str] = []
    if before.get('classification') != 'healthy':
        blockers.append(f"precheck service not healthy: {before.get('classification')}")
    if service.policy.report_only or not service.policy.restart_enabled:
        blockers.append('service policy does not allow restart')
    if service.policy.kill_enabled:
        blockers.append('kill_enabled must be false')
    if active['active']:
        blockers.append(f"active task guard found {len(active['active'])} active tasks")
    if active['source_failures'] and service.policy.active_task_query_failure_policy == 'defer':
        blockers.append('active-work source failed and defer policy is active')

    dry = execute_host_action(
        'systemctl_restart',
        service,
        policy_path=config.host_executor.policy_path,
        dry_run=True,
        reason=reason,
        confirmation_token=destructive_confirmation_token(service.service_id, 'systemctl_restart'),
    ).as_dict()
    if not dry.get('allowed'):
        blockers.append(f"executor dry-run denied: {dry.get('reason')}")

    executed = None
    after = None
    recovery_checks: list[dict[str, Any]] = []
    status = 'blocked'
    if not blockers and execute:
        executed = execute_host_action(
            'systemctl_restart',
            service,
            policy_path=config.host_executor.policy_path,
            dry_run=False,
            reason=reason,
            confirmation_token=destructive_confirmation_token(service.service_id, 'systemctl_restart'),
        ).as_dict()
        if executed.get('executed') and executed.get('returncode') == 0:
            time.sleep(max(0, settle_sec))
            after = check_service(service, config, persist=True).model_dump(mode='json')
            status = 'pass' if after.get('classification') == 'healthy' else 'failed_postcheck'
            recovery_checks: list[dict[str, Any]] = []
            if status != 'pass':
                deadline = time.time() + max(0, service.policy.startup_grace_sec - settle_sec)
                while time.time() < deadline:
                    time.sleep(5)
                    probe = check_service(service, config, persist=True).model_dump(mode='json')
                    recovery_checks.append({'checked_at': utc_now_iso(), 'classification': probe.get('classification'), 'reason': probe.get('reason')})
                    if probe.get('classification') == 'healthy':
                        after = probe
                        status = 'pass_recovered_within_grace'
                        break
        else:
            recovery_checks = []
            status = 'failed_execute'
    elif not blockers and not execute:
        status = 'dry_run_pass'

    report = {
        'schema': 'doghouse.restart_drill/v1',
        'service_id': service_id,
        'status': status,
        'execute': execute,
        'started_at': started_at,
        'finished_at': utc_now_iso(),
        'settle_sec': settle_sec,
        'reason': reason,
        'blockers': blockers,
        'before': before,
        'active_task_guard': active['result'],
        'executor_dry_run': dry,
        'executor_execution': executed,
        'after': after,
        'recovery_checks': recovery_checks,
        'rollback_hint': f'sudo systemctl restart {service.runtime.unit}' if service.runtime.unit else None,
    }
    if persist:
        root = Path(config.paths.state_dir) / 'drills'
        root.mkdir(parents=True, exist_ok=True)
        write_state_atomic(root / f'{service_id}-restart-drill.json', report)
        write_state_atomic(root / 'latest-restart-drill.json', report)
    return report
