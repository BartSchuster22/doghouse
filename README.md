# Doghouse

Doghouse is Watchdog v2: a Dockerized, API-first watchdog platform for Herman/Hermes operations and future agent frameworks.

Initial posture:

- report-only
- local-only API
- no restart capability
- no kill capability
- no host executor in Phase 0
- current production watchdog remains untouched

See `BUILD_STEPS.md` for the staged implementation plan.

## Quick local run

```bash
/home/herman/.local/bin/python3.11 -m venv .venv
. .venv/bin/activate
pip install -e .
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse
```

Then check:

```bash
curl http://127.0.0.1:18793/api/v1/status
curl http://127.0.0.1:18793/api/v1/services
curl -X POST http://127.0.0.1:18793/api/v1/services/hermes/check
```

CLI check:

```bash
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse check-service hermes
```

## Docker

```bash
docker compose up --build
```
