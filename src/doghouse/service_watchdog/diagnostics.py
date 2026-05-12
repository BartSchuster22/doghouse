from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlparse

from doghouse.common.service_config import ServiceConfig

REDACT_KEYS = ("token", "secret", "password", "authorization", "api_key", "apikey", "key")


def redact(value):
    if isinstance(value, dict):
        return {k: ("<redacted>" if any(part in k.lower() for part in REDACT_KEYS) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        text = value
        for marker in ("token=", "password=", "secret=", "api_key=", "apikey="):
            lower = text.lower()
            idx = lower.find(marker)
            if idx >= 0:
                end = text.find("&", idx)
                if end == -1:
                    text = text[: idx + len(marker)] + "<redacted>"
                else:
                    text = text[: idx + len(marker)] + "<redacted>" + text[end:]
        return text
    return value


def _tcp_probe(url: str, timeout_sec: float = 1.0) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {"url": url, "ok": None, "reason": "not an http(s) URL"}
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout_sec):
            return {"url": url, "host": parsed.hostname, "port": port, "tcp_connect_ok": True}
    except OSError as exc:
        return {"url": url, "host": parsed.hostname, "port": port, "tcp_connect_ok": False, "error": f"{type(exc).__name__}: {exc}"}


def collect_diagnostics(service: ServiceConfig) -> dict:
    """Collect safe, read-only diagnostics before any future action.

    Phase 3 is report-only: no process signals, restarts, or privileged commands.
    """
    loadavg = None
    try:
        loadavg = list(os.getloadavg())
    except OSError:
        pass

    proc_summary = {"proc_available": Path("/proc").exists()}
    if Path("/proc/meminfo").exists():
        try:
            lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()[:5]
            proc_summary["meminfo_head"] = lines
        except OSError as exc:
            proc_summary["meminfo_error"] = f"{type(exc).__name__}: {exc}"

    return redact({
        "service_id": service.service_id,
        "runtime": service.runtime.model_dump(),
        "endpoints": {name: _tcp_probe(url) for name, url in service.endpoints.items() if name in {"live", "ready", "health", "active_work"}},
        "host": {
            "hostname": socket.gethostname(),
            "loadavg": loadavg,
            "pid": os.getpid(),
        },
        "proc": proc_summary,
        "safety": {
            "report_only": service.policy.report_only,
            "restart_enabled": service.policy.restart_enabled,
            "kill_enabled": service.policy.kill_enabled,
        },
    })
