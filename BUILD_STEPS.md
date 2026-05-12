# Doghouse / Watchdog v2 build steps

Status: Phase 0 through Phase 8 implemented in repo. Hermes is prepared as the first cutover service; production timer enablement requires live-lane root approval/handoff.

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

## Safety defaults

- API binds to `127.0.0.1`.
- Report-only by default.
- Restart disabled by default.
- Kill disabled by default.
- Host executor absent until Phase 5.
- current production watchdog remains service-by-service during cutover
