# Doghouse Phase 17-20 Evidence Notes

## Phase 17 — QA 8/10 gate

CLI:

```bash
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml /opt/doghouse/.venv/bin/python -m doghouse.main qa-gate --threshold 8
```

API:

- `GET /api/v1/qa/gate`
- `POST /api/v1/qa/gate/run`

The gate scores Doghouse on a 10-point scale across service health, audit state, shadow state, scheduler freshness, path writability, executor hardening, devtask freshness, kill-disabled safety, no restart actions, and no incidents in the soak window. The gate passes at score >= 8.

## Phase 18 — Soak automation and daily evidence

CLI:

```bash
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml /opt/doghouse/.venv/bin/python -m doghouse.main daily-evidence --since 24h --threshold 8
```

API:

- `GET /api/v1/qa/evidence/daily`
- `POST /api/v1/qa/evidence/daily/run`

Systemd templates:

- `deploy/systemd/doghouse-daily-evidence.service`
- `deploy/systemd/doghouse-daily-evidence.timer`

Evidence outputs:

- `/srv/shared-memory/state/watchdog-v2/evidence/latest-daily-evidence.json`
- `/srv/shared-memory/state/watchdog-v2/evidence/latest-daily-evidence.md`

## Phase 19 — Test suite hardening

A pytest suite now covers:

- restart-grade liveness threshold classification
- degraded readiness classification
- minute-based soak windows
- endpoint mode parsing
- QA gate persistence
- daily evidence JSON/Markdown persistence

Run:

```bash
/opt/doghouse/.venv/bin/python -m pytest -q
```

## Phase 20 — Native endpoint split

Doghouse service configs now carry endpoint mode metadata:

- `native`
- `legacy_fallback`
- `not_supported`

OpenClaw is configured to use native split endpoints:

- `/live`
- `/ready`
- `/health`
- `/watchdog/active-work`

Hermes remains explicitly marked as legacy fallback for `/live` and `/ready` because Hermes currently exposes `/health` but not native `/live` or `/ready`.
