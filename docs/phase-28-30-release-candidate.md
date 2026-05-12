# Doghouse Phases 28-30 Evidence

## Phase 28 — Controlled restart drill

Controlled restart drill target: OpenClaw/Alice (`openclaw.service`).

Safety gates before execution:
- OpenClaw classified healthy by Doghouse.
- `kill_enabled=false`.
- `restart_enabled=true` and `report_only=false` for OpenClaw.
- Active task guard checked local Doghouse devtask heartbeats.
- OpenClaw `/watchdog/active-work` is currently marked `not_supported` because the route returns the frontend HTML shell rather than active-work JSON.
- Executor dry-run was allowed before execution.
- Destructive execution required operator reason and confirmation token.

Execution command pattern:

```bash
sudo env DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml \
  /opt/doghouse/.venv/bin/python -m doghouse.main restart-drill openclaw \
  --execute \
  --settle-sec 15 \
  --reason 'Phase 28 controlled OpenClaw restart drill approved by operator'
```

Result:
- `systemctl restart openclaw.service` executed through the hardened host executor.
- Executor return code: `0`.
- Initial 15 second postcheck was too short for OpenClaw and observed a transient `liveness_failed_below_threshold`.
- Extended verification inside the startup grace window confirmed OpenClaw returned to `healthy`.
- Final drill status: `pass_recovered_within_grace`.

Evidence:
- `/srv/shared-memory/state/watchdog-v2/drills/latest-restart-drill.json`
- `/srv/shared-memory/state/watchdog-v2/drills/openclaw-restart-drill.json`

## Phase 29 — Security and privilege review

Added CLI:

```bash
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse security-review
```

Added API:
- `GET /api/v1/security/review`
- `POST /api/v1/security/review/run`

Review scope:
- host executor allowlist
- destructive action reason/token requirements
- absolute binary requirement
- systemd unit regex gate
- restart cooldown
- audit hash-chain configuration
- per-service kill-disabled policy
- active-task guard policy
- selected file mode checks

Current result:
- status: `pass`
- score: `10.0 / 10`
- critical findings: `0`

Evidence:
- `/srv/shared-memory/state/watchdog-v2/security/latest-security-review.json`

## Phase 30 — Release candidate

Added CLI:

```bash
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse release-candidate
```

Added API:
- `GET /api/v1/release/candidate`
- `POST /api/v1/release/candidate/run`

Release candidate checks include:
- QA gate
- audit quality
- security review
- 24h soak report
- daily evidence
- artifact path summary

Evidence:
- `/srv/shared-memory/state/watchdog-v2/release/release-candidate.json`
- `/srv/shared-memory/state/watchdog-v2/release/release-candidate.md`

## OpenClaw active-work correction

During Phase 28, the previously configured OpenClaw active-work endpoint was verified to return the frontend HTML shell instead of JSON. The service config was corrected:

```yaml
endpoint_modes:
  active_work: not_supported
```

The endpoint was removed from OpenClaw's configured active-work source list until OpenClaw exposes a real JSON endpoint. Doghouse still checks local devtask heartbeat files before controlled restarts.
