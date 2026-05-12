# Doghouse / Watchdog v2 build steps

Status: staged implementation plan. No production watchdog cutover happens until explicitly approved.

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

## Phase 1 — service-watchdog report-only MVP

1. Add file-based service registry from `config/services.d/*.yaml`.
2. Add HTTP endpoint checker.
3. Add service classification model.
4. Add report-only decision engine.
5. Add atomic JSON state writer.
6. Add manual check endpoint: `POST /api/v1/services/{service_id}/check`.
7. Add service listing/status endpoints.
8. Add Hermes/OpenClaw config examples.
9. Verify no restart/kill action exists.
10. Commit and push Phase 1.

## Phase 2 — incidents and diagnostics

1. Add incident JSON/Markdown writer.
2. Add dedupe window.
3. Add pre-action diagnostics collection in report-only mode.
4. Add recent incidents API.
5. Add tests for incident output and redaction.
6. Commit and push Phase 2.

## Phase 3 — devtask-watchdog MVP

1. Add active-work API client.
2. Add heartbeat-file reader.
3. Add stuck/idle/orphaned classification.
4. Add checkpoint writer.
5. Add devtask API endpoints.
6. Keep kill/interrupt disabled.
7. Commit and push Phase 3.

## Phase 4 — watchdog-audit MVP

1. Add scheduler freshness checks.
2. Add policy validation checks.
3. Add state/log/incident writability checks.
4. Add old-watchdog migration-state checks.
5. Add audit API endpoint.
6. Commit and push Phase 4.

## Phase 5 — host executor

1. Add small whitelist-only host executor.
2. Add local socket/API client.
3. Add executor policy file.
4. Add tests proving unknown actions are rejected.
5. Keep restart disabled by default.
6. Commit and push Phase 5.

## Phase 6 — shadow mode

1. Run Doghouse beside current watchdog.
2. Compare old watchdog behavior with v2 report-only decisions.
3. Write migration report.
4. Fix mismatches.
5. Do not cut over yet.

## Phase 7 — service-by-service cutover

1. Pick one service.
2. Verify rollback command.
3. Explicitly enable restart for that service only after approval.
4. Disable old timer for that service.
5. Monitor.
6. Roll back if needed.

## Safety defaults

- API binds to `127.0.0.1`.
- Report-only by default.
- Restart disabled by default.
- Kill disabled by default.
- Host executor absent until Phase 5.
- Current live watchdog remains untouched.
