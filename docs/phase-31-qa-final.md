# Phase 31 — QA 10/10 final

## Objective

Reach a strict 10/10 Doghouse QA gate without hiding real failures, while preserving historical evidence.

## Changes

- Fixed shadow mode so healthy shadow runs are written only to state, not to the open incident directory.
- Added incident reconciliation for open records that are no longer actionable:
  - healthy shadow reports previously misfiled under `incidents/open`
  - resolved shadow attention records when the current shadow result is `ok`
  - legacy watchdog records after Doghouse cutover
  - recovered service incidents when the current service classification is `healthy`
- Reconciliation moves files to archive/resolved folders; it does not delete evidence.
- Added CLI/API support for reconciliation.

## CLI

```bash
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse incident-reconcile
DOGHOUSE_CONFIG=/opt/doghouse/config/local.yaml doghouse qa-gate --threshold 10
```

## API

```text
POST /api/v1/incidents/reconcile
GET /api/v1/qa/gate
POST /api/v1/qa/gate/run
```

## Evidence

Latest reconciliation:

```text
/srv/shared-memory/state/watchdog-v2/incidents/latest-reconciliation.json
```

Latest QA gate:

```text
/srv/shared-memory/state/watchdog-v2/qa/latest-qa-gate.json
```

## Final result

The Phase 31 gate requires every weighted item to pass:

- registered services healthy
- audit OK
- shadow OK
- scheduler freshness OK
- paths writable
- executor policy hardened
- devtask state OK
- kill disabled everywhere
- no restart actions in soak window
- no open incidents in soak window

Current final QA result:

```text
status: pass
score: 10.0 / 10
threshold: 10.0
```
