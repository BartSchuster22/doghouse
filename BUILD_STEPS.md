# Doghouse / Watchdog v2 build steps

Status: Phase 0 through Phase 20 implemented in repo. Hermes and OpenClaw are cut over to Doghouse timers; old service watchdog timers are disabled and rollback commands are documented.

## Phase 0 — repository and skeleton

1. Clone GitHub repo using the deployed SSH key.
2. Add project README and build steps.
3. Add Python package skeleton.
4. Add Dockerfile and docker-compose.yml.
5. Add local-only API server with `/api/v1/status`.
6. Add config loader and example configs.
7. Add structured logging bootstrap.
8. Add filesystem bootstrap for state/logs/incidents/checkpoints.
9. Verify syntax/imports.
10. Commit and push Phase 0 skeleton.

## Phase 1 — service registry MVP

1. Add file-based service registry from `config/services.d/*.yaml`.
2. Add service config validation models.
3. Add service listing/status endpoints.
4. Add Hermes/OpenClaw config examples.
5. Verify restart/kill remain disabled.
6. Commit and push Phase 1.

## Phase 2 — HTTP checker and classifications

1. Add HTTP endpoint checker for `/live`, `/ready`, and `/health`.
2. Add service classification model.
3. Add report-only decision engine.
4. Add consecutive liveness failure counter.
5. Add atomic JSON state writer.
6. Add manual check endpoint: `POST /api/v1/services/{service_id}/check`.
7. Add CLI check command: `doghouse check-service [service_id]`.
8. Verify no restart/kill action exists.
9. Commit and push Phase 2.

## Phase 3 — incidents and diagnostics

1. Add incident JSON/Markdown writer.
2. Add dedupe window.
3. Add pre-action diagnostics collection in report-only mode.
4. Add recent incidents API.
5. Add tests for incident output and redaction.
6. Commit and push Phase 3.

## Phase 4 — devtask-watchdog MVP

1. Add active-work API client.
2. Add heartbeat-file reader.
3. Add stuck/idle/orphaned classification.
4. Add checkpoint writer.
5. Add devtask API endpoints.
6. Keep kill/interrupt disabled.
7. Commit and push Phase 4.

## Phase 5 — watchdog-audit MVP

1. Add scheduler freshness checks.
2. Add policy validation checks.
3. Add state/log/incident writability checks.
4. Add old-watchdog migration-state checks.
5. Add audit API endpoint.
6. Commit and push Phase 5.

## Phase 6 — host executor

1. Add small whitelist-only host executor.
2. Add local socket/API client.
3. Add executor policy file.
4. Add tests proving unknown actions are rejected.
5. Keep restart disabled by default.
6. Commit and push Phase 6.

## Phase 7 — shadow mode

1. Run Doghouse beside current watchdog. Completed via `doghouse shadow-once` plus `doghouse-shadow.service/timer` units in `deploy/systemd/`.
2. Compare old watchdog behavior with v2 report-only decisions. Completed in `shadow_once` report output.
3. Write migration report. Completed under `state_dir/shadow/last-shadow-report.json` and incident JSON snapshots.
4. Fix mismatches. Current Hermes mismatch is resolved by using `/health` as the temporary liveness source until native `/live` exists; OpenClaw remains report-only under old watchdog.
5. Do not cut over yet. Completed before Phase 8 precheck.

## Phase 8 — service-by-service cutover

1. Pick one service. Hermes selected first because OpenClaw health is currently connection-refused and remains in old-watchdog mode.
2. Verify rollback command. Hermes rollback: `systemctl enable --now watchdog-hermes.timer`.
3. Explicitly enable restart for that service only after approval. Hermes config now has `report_only: false` and `restart_enabled: true`; kill remains disabled.
4. Disable old timer for that service. Cutover manager supports this with `doghouse cutover-service hermes --execute`; live execution requires root/live-lane approval.
5. Monitor. Use `systemctl list-timers 'doghouse*' 'watchdog-*' --all --no-pager`, `journalctl -u doghouse-check@hermes.service`, and `doghouse shadow-once`.
6. Roll back if needed. Run `systemctl enable --now watchdog-hermes.timer` and `systemctl disable --now doghouse-check@hermes.timer`.

## Phase 9 — stabilization soak

1. Add `doghouse soak-report --since 24h` for persisted post-cutover evidence.
2. Add `GET /api/v1/soak` for API access to the latest soak report.
3. Summarize current service states, shadow state, audit state, recent incidents, and journal evidence when available.
4. Persist latest soak evidence under `state_dir/soak/latest-soak-report.json`.

## Phase 10 — native service endpoint cleanup

1. Verify Hermes currently exposes `/health` only; keep `/health` as temporary live/ready/health source until Hermes implements native `/live` and `/ready`.
2. Repair OpenClaw endpoint config from stale `127.0.0.1:8081` to live OpenClaw gateway `127.0.0.1:18789`.
3. Configure OpenClaw readiness via `http://127.0.0.1:18789/ready` and restart-grade liveness via the known-good `http://127.0.0.1:18789/health` endpoint.
4. Keep kill disabled.

## Phase 11 — OpenClaw/Alice repair before cutover

1. Confirm `openclaw.service` is active.
2. Confirm port `18789` is listening and returns healthy `/ready` and `/health` responses.
3. Confirm Doghouse classifies OpenClaw healthy before cutover.

## Phase 12 — OpenClaw service-by-service cutover

1. Enable Doghouse OpenClaw policy: `report_only: false`, `restart_enabled: true`, `kill_enabled: false`.
2. Enable `doghouse-check@openclaw.timer`.
3. Disable `watchdog-openclaw.timer` after healthy Doghouse precheck.
4. Rollback command: `systemctl enable --now watchdog-openclaw.timer && systemctl disable --now doghouse-check@openclaw.timer`.

## Phase 13 — host executor hardening

1. Require absolute executable paths for every whitelisted action.
2. Restrict executable paths to an explicit `allowed_binaries` list.
3. Reject invalid systemd unit names with a regex gate.
4. Mark destructive actions and require explicit execution intent.
5. Keep restart gated by per-service policy and add restart cooldown.
6. Run commands with a scrubbed environment, `cwd=/`, `shell=False`, and bounded output.
7. Append every allow/deny/dry-run/execution result to an executor audit JSONL log.

## Phase 14 — devtask-watchdog integration

1. Add `doghouse-devtasks.service` and `doghouse-devtasks.timer` templates.
2. Merge active-work API results with heartbeat files.
3. Persist `devtasks/last-check.json` on each scheduled check.
4. Keep kill/interrupt disabled and write checkpoints for idle/stuck/orphaned/unknown tasks.

## Phase 15 — watchdog audit completion

1. Audit Doghouse systemd timers and old watchdog timer states.
2. Audit executor hardening policy.
3. Audit devtask-state freshness.
4. Audit shadow-state freshness.
5. Keep audit report persisted under `state_dir/audit/last-audit.json`.

## Phase 16 — documentation and operator runbook

1. Add `docs/operator-runbook.md`.
2. Document status checks, timer checks, API checks, host executor use, devtask heartbeat schema, incident/state paths, and rollback commands.

## Phase 17 — QA 8/10 gate

1. Add `doghouse qa-gate --threshold 8`.
2. Add API endpoints `GET /api/v1/qa/gate` and `POST /api/v1/qa/gate/run`.
3. Score service health, audit, shadow, scheduler freshness, path writability, executor hardening, devtask freshness, kill-disabled safety, restart actions, and incidents.
4. Persist latest QA evidence under `state_dir/qa/latest-qa-gate.json`.

## Phase 18 — soak automation and daily evidence

1. Add `doghouse daily-evidence --since 24h --threshold 8`.
2. Add API endpoints `GET /api/v1/qa/evidence/daily` and `POST /api/v1/qa/evidence/daily/run`.
3. Add `doghouse-daily-evidence.service` and `doghouse-daily-evidence.timer` templates.
4. Persist JSON and Markdown evidence under `state_dir/evidence/`.

## Phase 19 — test suite hardening

1. Add pytest optional dependency and pytest configuration.
2. Add tests for classification, soak window parsing, endpoint mode parsing, QA gate persistence, and daily evidence persistence.
3. Keep tests non-destructive and local-only.

## Phase 20 — native endpoint split

1. Add endpoint mode metadata: `native`, `legacy_fallback`, `not_supported`.
2. Switch OpenClaw liveness to native `/live` and add native active-work endpoint.
3. Mark Hermes `/live` and `/ready` as legacy fallback to `/health` until Hermes exposes native endpoints.
4. Document split endpoint state in `docs/phase-17-20-evidence.md`.

## Phase 21 — OpenClaw/Alice repair and readiness

1. Add `doghouse openclaw-readiness`.
2. Add `/api/v1/readiness/openclaw` and `/api/v1/readiness/openclaw/run`.
3. Verify OpenClaw service, native endpoints, policy, and timer state.
4. Persist readiness evidence under `state_dir/readiness/openclaw.json`.

## Phase 22 — OpenClaw/Alice cutover

1. Verify OpenClaw Doghouse check is healthy.
2. Keep `report_only: false`, `restart_enabled: true`, and `kill_enabled: false`.
3. Keep `doghouse-check@openclaw.timer` active.
4. Disable `watchdog-openclaw.timer`.
5. Document rollback command.

## Phase 23 — Host executor hardening v2

1. Require operator reason for destructive actions.
2. Require confirmation token for destructive actions.
3. Return required token in dry-run/deny output.
4. Add executor audit hash chain.
5. Extend audit checks for v2 executor hardening policy.
6. Add tests for destructive-action gating and audit hash output.

## Phase 24 — Devtask heartbeat integration

1. Add `doghouse devtask-heartbeat` for writing normalized heartbeat files.
2. Add heartbeat submission/prune APIs under `/api/v1/devtasks/heartbeats`.
3. Normalize heartbeat schema to `doghouse.devtask.heartbeat/v1` with `heartbeat_hash`.
4. Keep devtask watchdog report-only with kill/interrupt disabled.

## Phase 25 — Audit quality upgrade

1. Add top-level audit quality score, issue counts, and recommendations.
2. Add executor audit-chain inspection.
3. Add notification layer health checks.
4. Keep audit output persisted under `state_dir/audit/last-audit.json`.

## Phase 26 — Notification layer

1. Add local-outbox notifications under `state_dir/notifications/`.
2. Add CLI commands `doghouse notification-status` and `doghouse notify`.
3. Add APIs `/api/v1/notifications/status`, `/send`, and `/test`.
4. Add systemd templates for optional notification sweep.
5. External delivery remains disabled unless explicitly approved later.

## Phase 27 — Operator runbook and docs finalization

1. Add `docs/phase-24-27-evidence.md`.
2. Update operator docs with devtask heartbeat, audit quality, and notification commands.
3. Re-run compile, tests, live Doghouse checks, audit, QA gate, and git clean verification.

## Safety defaults

- API binds to `127.0.0.1`.
- Report-only by default.
- Restart disabled by default.
- Kill disabled by default.
- Host executor restricted to whitelist-only actions.
- Current production watchdog rollback timers remain installed but disabled after service-by-service cutover.

## Phase 28 — Controlled restart drill

- Added `doghouse restart-drill <service_id>` with dry-run and execute modes.
- The drill checks service health, restart policy, kill-disabled policy, active task guard, executor dry-run, and post-restart health.
- Executed a controlled OpenClaw restart through the hardened host executor using sudo/root context.
- OpenClaw restart returned `0`; initial 15s postcheck was early, and extended startup-grace verification confirmed healthy.
- Evidence: `/srv/shared-memory/state/watchdog-v2/drills/latest-restart-drill.json`.

## Phase 29 — Security and privilege review

- Added `doghouse security-review`.
- Added API routes `/api/v1/security/review` and `/api/v1/security/review/run`.
- Review covers host executor allowlists, destructive reason/token requirements, audit hash-chain, restart cooldown, kill-disabled policies, active-task guard policy, and selected file modes.
- Current result: pass, 10.0/10, 0 critical findings.

## Phase 30 — Release candidate

- Added `doghouse release-candidate`.
- Added API routes `/api/v1/release/candidate` and `/api/v1/release/candidate/run`.
- Release candidate aggregates QA gate, audit, security review, daily evidence, soak report, commit, and artifact paths.
- Evidence: `/srv/shared-memory/state/watchdog-v2/release/release-candidate.json` and `.md`.

## Phase 28 correction

- Corrected OpenClaw `active_work` endpoint mode to `not_supported`; the previous route returned frontend HTML, not JSON active-work data.
- Doghouse still uses local devtask heartbeat files for active-task guard until OpenClaw exposes native JSON `/watchdog/active-work`.

## Phase 31 — QA 10/10 final

- Added incident reconciliation so false-open/resolved records are archived without deleting evidence.
- Fixed shadow mode to stop writing healthy shadow reports into incidents/open.
- Added CLI: `doghouse incident-reconcile`.
- Added API: `POST /api/v1/incidents/reconcile`.
- Final QA command: `DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse qa-gate --threshold 10`.
- Evidence: `/srv/shared-memory/state/watchdog-v2/qa/latest-qa-gate.json`.
- Result: pass, 10.0/10.
