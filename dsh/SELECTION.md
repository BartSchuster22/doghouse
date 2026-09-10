# Doghouse DSH successor selection — Stage 5 candidate

Status: selected design and implementation candidate, NOT live-qualified yet.

## Canonical selection

`doghouse/dsh/doghouse_dsh` is the single selected DSH successor. Legacy Doghouse
v2 remains unchanged; this is not permission to run its executor on DSH.

The only reused vNext executable source is the pure health-contract normalizer:
`/srv/doghouse-rebuild/vnext/src/doghouse_vnext/health_contracts.py`, input SHA-256
`0c609ee3403547266a89bfeb4251d9bb59464cd5f6c1f43ee50b23bf97b4f144`.
It has no process, network, persistence, shell, recipe or LLM execution authority.
The selected copy fails closed on empty contracts, missing active-work observations
and missing custom status. Its generic detail maps are NOT serialized into reports.
Health normalization never grants recovery authority by itself.

Rejected for reuse: legacy v2 executor and recipes; vNext recovery recipes,
validators/automation/stateful executors not proven under this DSH owner/lifecycle
contract; old operator write paths. No recipe may supply a command, filesystem
path, unit name, Docker selector, container ID or host/daemon restart.

## Three separate authority layers

1. Host-native unprivileged observer, Unix socket only; no Docker group/socket.
2. Root broker: source-fixed operations and exact cell/image/mount/owner checks,
   Linux peer credentials, shared installation lock, persistent reservations and
   cooldowns. Only Hermes, Core and Memory can be auto-recovered. Other services,
   the Docker daemon and host reboot require their explicit operator/lifecycle owner.
3. Core + UNIUI: authenticated `operations.read` status/audit projection only;
   no privileged socket or command endpoint, unknown/stale reports never green.

The local admin can persist maintenance intent or acknowledge a recovery circuit.
Lifecycle stop/uninstall must set maintenance under the same operations mutex.
Initial install uses the existing Stage 2 protocol before enrolling the observer.
A durable issued recovery action consumes the budget before its external effect;
interruption makes it uncertain and blocks automatic repeats until acknowledged.
Native business stores remain authoritative; recovery never replays model, callback,
Memory or application effects itself. It may restart a stopped executor, but never
kills running Hermes when native work is active or cannot be observed safely.

## Required qualification (not yet claimed)

Unit/security/contract tests plus installed-cell interruption evidence for Hermes,
Core, Memory, provider failure, isolated Docker daemon failure, isolated guest
reboot, storage pressure, repeated recovery, maintenance and lifecycle races.
Real application/workflow owner and deduplication assertions must accompany the
infrastructure observations. Process presence alone is not acceptance.
