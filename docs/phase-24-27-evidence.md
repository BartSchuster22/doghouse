# Doghouse Phases 24-27 Evidence

## Phase 24 — Devtask heartbeat integration

Added a first-class heartbeat write path for Herman/agent/dev tasks.

CLI:

```bash
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse devtask-heartbeat <task_id> --status active --progress "message" --pid $$
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse prune-devtask-heartbeats --max-age-sec 86400
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse check-devtasks
```

API:

- `GET /api/v1/devtasks/heartbeats`
- `POST /api/v1/devtasks/heartbeats`
- `POST /api/v1/devtasks/heartbeats/prune`
- `POST /api/v1/devtasks/check`

Heartbeat files are normalized to schema `doghouse.devtask.heartbeat/v1`, receive a stable `heartbeat_hash`, and remain report-only. Doghouse still does not kill or interrupt tasks.

## Phase 25 — Audit quality upgrade

Audit now includes:

- audit quality score
- critical/warning issue counts
- operator recommendations
- executor audit-chain inspection
- notification layer health

The audit output now has a top-level `quality` object in addition to section-level results.

## Phase 26 — Notification layer

Added a safe local notification layer. It writes structured JSONL events to a local outbox rather than directly calling external chat/webhook systems.

CLI:

```bash
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse notification-status
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse notify --source operator --severity warning --title "Test" --summary "Notification test" --force
```

API:

- `GET /api/v1/notifications/status`
- `POST /api/v1/notifications/send`
- `POST /api/v1/notifications/test`

State:

- `/srv/shared-memory/state/watchdog-v2/notifications/outbox.jsonl`
- `/srv/shared-memory/state/watchdog-v2/notifications/latest.json`

Systemd templates added:

- `doghouse-notification-sweep.service`
- `doghouse-notification-sweep.timer`

The sweep timer is intentionally low-risk: it only writes local notification evidence.

## Phase 27 — Operator runbook and docs finalization

Updated operator-facing documentation with heartbeat, audit quality, and notification commands. Doghouse remains safe-by-default:

- no kill path enabled
- no task interrupt path enabled
- host executor still whitelist-only
- destructive host actions still require reason + confirmation token
- notifications are local outbox only unless a future explicit external delivery adapter is approved
