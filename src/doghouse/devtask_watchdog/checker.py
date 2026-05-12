from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from doghouse.common.config import DoghouseConfig, load_config_from_env
from doghouse.service_watchdog.state import utc_now_iso


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def heartbeat_dir(config: DoghouseConfig) -> Path:
    return Path(config.paths.state_dir) / "devtasks" / "heartbeats"


def checkpoint_file(config: DoghouseConfig, task_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in task_id)[:120]
    return Path(config.paths.checkpoint_dir) / f"{safe}.json"


def fetch_active_work(url: str | None, timeout_sec: int = 5) -> dict[str, Any]:
    if not url:
        return {"ok": False, "reason": "active-work URL not configured", "tasks": []}
    try:
        response = httpx.get(url, timeout=timeout_sec)
        response.raise_for_status()
        data = response.json()
        tasks = data.get("tasks", data if isinstance(data, list) else [])
        if not isinstance(tasks, list):
            tasks = []
        return {"ok": True, "url": url, "tasks": tasks}
    except Exception as exc:
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}", "tasks": []}


def read_heartbeats(config: DoghouseConfig) -> list[dict[str, Any]]:
    root = heartbeat_dir(config)
    if not root.exists():
        return []
    items = []
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        data.setdefault("task_id", path.stem)
        data["heartbeat_path"] = str(path)
        items.append(data)
    return items


def classify_task(task: dict[str, Any], now: datetime | None = None, idle_sec: int = 900, orphaned_sec: int = 3600) -> tuple[str, str]:
    now = now or datetime.now(timezone.utc)
    last_seen = _parse_iso(str(task.get("last_seen_at") or task.get("updated_at") or task.get("heartbeat_at") or ""))
    status = str(task.get("status") or "active")
    if status in {"completed", "cancelled", "failed"}:
        return status, f"task status is {status}"
    if last_seen is None:
        return "unknown", "no parseable heartbeat timestamp"
    age = (now - last_seen).total_seconds()
    if age >= orphaned_sec:
        return "orphaned", f"last heartbeat {int(age)}s ago"
    if age >= idle_sec:
        return "idle", f"last heartbeat {int(age)}s ago"
    if task.get("expected_progress_at"):
        expected = _parse_iso(str(task.get("expected_progress_at")))
        if expected and now > expected:
            return "stuck", "expected progress timestamp has passed"
    return "active", f"last heartbeat {int(age)}s ago"


def write_checkpoint(config: DoghouseConfig, task: dict[str, Any], classification: str, reason: str) -> str:
    task_id = str(task.get("task_id") or task.get("id") or "unknown-task")
    payload = {
        "task_id": task_id,
        "created_at": utc_now_iso(),
        "classification": classification,
        "reason": reason,
        "mode": "report-only",
        "kill_enabled": False,
        "interrupt_enabled": False,
        "task": task,
    }
    path = checkpoint_file(config, task_id)
    _atomic_write(path, payload)
    return str(path)


def check_devtasks(config: DoghouseConfig | None = None, active_work_url: str | None = None, persist: bool = True) -> dict[str, Any]:
    config = config or load_config_from_env()
    active_work = fetch_active_work(active_work_url)
    tasks: dict[str, dict[str, Any]] = {}
    for task in active_work.get("tasks", []):
        if isinstance(task, dict):
            task_id = str(task.get("task_id") or task.get("id") or len(tasks))
            task["task_id"] = task_id
            tasks[task_id] = task
    for task in read_heartbeats(config):
        task_id = str(task.get("task_id") or task.get("id") or len(tasks))
        tasks[task_id] = {**tasks.get(task_id, {}), **task, "task_id": task_id}

    checked = []
    for task in tasks.values():
        classification, reason = classify_task(task)
        checkpoint_path = None
        if persist and classification in {"stuck", "idle", "orphaned", "unknown"}:
            checkpoint_path = write_checkpoint(config, task, classification, reason)
        checked.append({"task_id": task.get("task_id"), "classification": classification, "reason": reason, "checkpoint_path": checkpoint_path, "kill_enabled": False, "interrupt_enabled": False, "task": task})

    result = {
        "checked_at": utc_now_iso(),
        "mode": "report-only",
        "active_work": {k: v for k, v in active_work.items() if k != "tasks"},
        "task_count": len(checked),
        "tasks": checked,
        "kill_enabled": False,
        "interrupt_enabled": False,
    }
    if persist:
        _atomic_write(Path(config.paths.state_dir) / "devtasks" / "last-check.json", result)
    return result
