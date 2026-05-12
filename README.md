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
python -m venv .venv
. .venv/bin/activate
pip install -e .
doghouse
```

Then check:

```bash
curl http://127.0.0.1:18793/api/v1/status
```

## Docker

```bash
docker compose up --build
```
