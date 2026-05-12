# Doghouse

Doghouse is Watchdog v2: a Dockerized, API-first watchdog platform for Herman/Hermes operations and future agent frameworks.

Initial posture:

- report-only
- local-only API
- no restart capability
- no kill capability
- no host executor before Phase 6
- whitelist-only host executor
- service-by-service cutover; kill remains disabled
- old production watchdog is migrated service-by-service with documented rollback

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
curl http://127.0.0.1:18793/api/v1/incidents
curl -X POST http://127.0.0.1:18793/api/v1/devtasks/check
curl -X POST http://127.0.0.1:18793/api/v1/audit/run
curl http://127.0.0.1:18793/api/v1/executor/policy
curl -X POST http://127.0.0.1:18793/api/v1/shadow/run
curl http://127.0.0.1:18793/api/v1/soak
```

CLI check:

```bash
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse check-service hermes
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse check-devtasks
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse audit
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse executor hermes systemctl_show
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse shadow-once
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse soak-report --since 24h
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse cutover-service hermes
```

## Docker

```bash
docker compose up --build
```
