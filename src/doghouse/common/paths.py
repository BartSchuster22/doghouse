from __future__ import annotations

from pathlib import Path

from doghouse.common.config import PathsConfig


def bootstrap_paths(paths: PathsConfig) -> None:
    for raw in [paths.state_dir, paths.incident_dir, paths.log_dir, paths.checkpoint_dir]:
        Path(raw).mkdir(parents=True, exist_ok=True)


def path_status(paths: PathsConfig) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for name, raw in {
        "state_dir": paths.state_dir,
        "incident_dir": paths.incident_dir,
        "log_dir": paths.log_dir,
        "checkpoint_dir": paths.checkpoint_dir,
    }.items():
        path = Path(raw)
        result[name] = {
            "path": str(path),
            "exists": path.exists(),
            "is_dir": path.is_dir(),
            "writable": path.exists() and path.is_dir(),
        }
    return result
