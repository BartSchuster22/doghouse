from __future__ import annotations

import os

import uvicorn

from doghouse.common.config import load_config
from doghouse.common.paths import bootstrap_paths


def main() -> None:
    config_path = os.environ.get("DOGHOUSE_CONFIG", "config/watchdog.yaml")
    config = load_config(config_path)
    bootstrap_paths(config.paths)
    uvicorn.run(
        "doghouse.api.app:create_app",
        factory=True,
        host=config.api.bind,
        port=config.api.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
