# Doghouse operator runbook

## Status
Doghouse is the active watchdog layer for Hermes and OpenClaw. Old `watchdog-hermes.timer` and `watchdog-openclaw.timer` are kept installed for rollback but disabled.

## Safety invariants
- `kill_enabled` must remain false.
- Host executor is whitelist-only and uses absolute argv paths.
- Destructive actions require explicit `--execute` and service restart policy.
- Restart actions are audited to `/srv/shared-memory/logs/watchdog-v2/executor-audit.jsonl`.
- Service checks, devtask checks, shadow checks, audits, incidents, and soak reports persist under `/srv/shared-memory`.

## Routine checks

```bash
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml /opt/doghouse/.venv/bin/python -m doghouse.main check-service
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml /opt/doghouse/.venv/bin/python -m doghouse.main check-devtasks
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml /opt/doghouse/.venv/bin/python -m doghouse.main shadow-once
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml /opt/doghouse/.venv/bin/python -m doghouse.main audit
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml /opt/doghouse/.venv/bin/python -m doghouse.main soak-report --since 24h
```

## Timer checks

```bash
systemctl list-timers 'doghouse*' 'watchdog-*' --all --no-pager
systemctl status doghouse-check@hermes.timer doghouse-check@openclaw.timer doghouse-devtasks.timer doghouse-shadow.timer doghouse-audit.timer --no-pager
```

Expected:
- `doghouse-check@hermes.timer`: active/enabled
- `doghouse-check@openclaw.timer`: active/enabled
- `doghouse-devtasks.timer`: active/enabled
- `doghouse-shadow.timer`: active/enabled
- `doghouse-audit.timer`: active/enabled
- `watchdog-hermes.timer`: inactive/disabled
- `watchdog-openclaw.timer`: inactive/disabled

## API checks

```bash
curl http://127.0.0.1:18793/api/v1/status
curl http://127.0.0.1:18793/api/v1/services
curl http://127.0.0.1:18793/api/v1/devtasks/status
curl http://127.0.0.1:18793/api/v1/audit
curl http://127.0.0.1:18793/api/v1/soak
```

## Host executor

Dry-run show:

```bash
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml /opt/doghouse/.venv/bin/python -m doghouse.main executor hermes systemctl_show
```

Manual restart, only when intentionally approved:

```bash
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml /opt/doghouse/.venv/bin/python -m doghouse.main executor hermes systemctl_restart --execute
```

The executor refuses unknown actions, non-whitelisted services, non-absolute argv, shell metacharacters, invalid unit names, restart without service policy, and restarts inside the cooldown window.

## Devtask watchdog integration

Heartbeat directory:

```bash
/srv/shared-memory/state/watchdog-v2/devtasks/heartbeats/*.json
```

Minimum heartbeat shape:

```json
{
  "task_id": "example-task",
  "status": "active",
  "heartbeat_at": "2026-05-12T17:00:00+00:00",
  "last_progress_at": "2026-05-12T17:00:00+00:00",
  "pid": 12345,
  "repo": "/opt/doghouse",
  "command": "pytest",
  "current_phase": "tests"
}
```

Classifications:
- `active`: recent heartbeat/progress
- `idle`: heartbeat stale but below orphan threshold
- `stuck`: expected progress missed or no progress beyond stuck threshold
- `orphaned`: pid missing or heartbeat too old
- `unknown`: unreadable or malformed heartbeat
- `completed`, `cancelled`, `failed`: passed through

Idle/stuck/orphaned/unknown tasks write checkpoints to `/srv/shared-memory/checkpoints/interrupted-tasks`.

## Rollback

Hermes rollback:

```bash
systemctl enable --now watchdog-hermes.timer && systemctl disable --now doghouse-check@hermes.timer
```

OpenClaw rollback:

```bash
systemctl enable --now watchdog-openclaw.timer && systemctl disable --now doghouse-check@openclaw.timer
```

Full Doghouse timer pause:

```bash
systemctl disable --now doghouse-check@hermes.timer doghouse-check@openclaw.timer doghouse-devtasks.timer doghouse-shadow.timer doghouse-audit.timer
```

## Incident/state locations

- Service state: `/srv/shared-memory/state/watchdog-v2/services/*.json`
- Devtask state: `/srv/shared-memory/state/watchdog-v2/devtasks/last-check.json`
- Shadow state: `/srv/shared-memory/state/watchdog-v2/shadow/last-shadow-report.json`
- Audit state: `/srv/shared-memory/state/watchdog-v2/audit/last-audit.json`
- Soak state: `/srv/shared-memory/state/watchdog-v2/soak/latest-soak-report.json`
- Incidents: `/srv/shared-memory/incidents/open`
- Executor audit log: `/srv/shared-memory/logs/watchdog-v2/executor-audit.jsonl`
