# Doghouse phases 21-23 evidence

## Phase 21 — OpenClaw/Alice repair and readiness

Implemented `doghouse openclaw-readiness` and `/api/v1/readiness/openclaw` readiness reporting.

Readiness gates:
- `openclaw.service` active.
- Native OpenClaw endpoints healthy: `/live`, `/ready`, `/health`, `/watchdog/active-work`.
- Doghouse service check classifies OpenClaw as `healthy`.
- Policy is cutover-safe: `report_only: false`, `restart_enabled: true`, `kill_enabled: false`, active-task guard enabled.
- Doghouse timer active and old watchdog timer inactive.

Latest persisted report:
`/srv/shared-memory/state/watchdog-v2/readiness/openclaw.json`

## Phase 22 — OpenClaw/Alice cutover

OpenClaw is cut over to Doghouse service checks.

Current intended timer state:
- `doghouse-check@openclaw.timer`: active
- `watchdog-openclaw.timer`: inactive
- `openclaw.service`: active

Rollback command:

```bash
sudo systemctl enable --now watchdog-openclaw.timer && sudo systemctl disable --now doghouse-check@openclaw.timer
```

## Phase 23 — Host executor hardening v2

Added second-layer executor safety controls:

- Destructive actions require an operator reason.
- Destructive actions require a service/action confirmation token, e.g. `EXECUTE:openclaw:systemctl_restart`.
- The required token is returned in deny/dry-run results for operator visibility.
- Executor audit JSONL now includes a hash chain (`previous_audit_hash`, `audit_hash`) for tamper-evident review.
- Audit policy checks now flag missing destructive reason/token requirements and disabled audit hash chain.

Safety retained:
- whitelist-only actions
- absolute argv0 requirement
- allowed binary list
- unit-name regex
- shell disabled
- scrubbed environment
- restart cooldown
- per-service restart policy gate
- kill disabled
