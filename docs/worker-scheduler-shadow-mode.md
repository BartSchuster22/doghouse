# Doghouse worker scheduler shadow/report-only mode

Status: implementation note for Kanban task t_a5e52a92. No live deploy, timer disablement, host restart, or destructive notification action is approved by this document.

## Entrypoints

- `doghouse worker` runs the long-lived single-process scheduler.
- `doghouse worker --once` runs each configured job once and exits.
- `doghouse worker --once --dry-run` prints the planned jobs without invoking job side effects.
- `doghouse worker --print-schedule` prints schedule parity metadata.
- `doghouse-worker` is installed as a console-script alias for the same entrypoint.

The Docker Compose worker service uses the same application image as the API service and runs:

```text
doghouse worker
```

## Schedule parity

The first worker schedule intentionally mirrors the current Doghouse timer responsibilities without disabling or replacing host timers yet:

| Worker job | Default cadence | Existing responsibility covered | Behavior |
| --- | ---: | --- | --- |
| `service-checks` | 60s | `doghouse-check@*.timer` service checks | Runs `check_service(..., persist=True)` for each configured service. |
| `devtasks` | 60s | `doghouse-devtasks.timer` | Runs devtask watchdog persistence. |
| `audit` | 300s | `doghouse-audit.timer` | Runs audit persistence and emits local-outbox audit notification through existing dedupe. |
| `notification-status` | 300s | `doghouse-notification-sweep.timer` status visibility | Reads notification status only. |
| `notification-sweep` | 900s | `doghouse-notification-sweep.timer` sweep visibility | Emits a low-severity local-outbox heartbeat through existing dedupe; no force send and no destructive delivery action. |
| `shadow-once` | 300s | `doghouse-shadow.timer` | Runs shadow comparison persistence. |
| `daily-evidence` | 86400s | `doghouse-daily-evidence.timer` | Generates the 24h evidence bundle with threshold 8.0. |
| `incident-reconcile` | 300s | Incident reconciliation periodic work from the rebuild plan | Reconciles open incidents using existing report-only logic. |
| `openclaw-readiness` | 300s | OpenClaw readiness periodic work from the rebuild plan | Writes readiness evidence while forcing the nested service check into report-only mode. |

Cadences are configurable in `scheduler:` in `config/local.yaml` and `config/watchdog.yaml`.

## Shadow/report-only safety

The worker does not schedule `doghouse executor`, `doghouse restart-drill`, or `doghouse cutover-service`, and it never passes `--execute` to any command path. Host restart authority remains host-side and report-only until a separately reviewed executor bridge is approved.

`service-checks` and worker-scheduled `openclaw-readiness` force loaded service config into a worker-local shadow copy before calling the shared service checker:

```text
policy.report_only = true
policy.restart_enabled = false
policy.kill_enabled = false
```

This is deliberate because the canonical host-side service configs may allow restarts for the existing host watchdog path. The worker must not inherit that authority; even if a liveness threshold is met, the resulting action is a non-executed `systemctl_restart` recommendation with reason `report-only or restart disabled`.

Audit notifications use the existing local outbox dedupe path. The worker does not use `--force` and does not bypass `notifications.dedupe_window_sec`.

## Overlap prevention

The scheduler is single-process and runs jobs serially. Each job also takes an atomic per-job lock file under:

```text
<state_dir>/worker-locks/<job>.lock
```

If another worker process or manual `--once` run already holds the same job lock, the job reports `skipped_locked` and does not run. Lock files include `pid`, `job`, and `created_at` so an operator can inspect stale locks manually instead of the worker guessing and breaking locks unsafely.

## Non-actions confirmed

This implementation does not:

- disable, enable, restart, or edit any systemd timer or service
- run Docker Compose up/down or deploy containers
- execute host restarts
- add a privileged container, host PID namespace, DBus mount, or `/run/systemd/private` mount
- force notifications or bypass local-outbox dedupe
