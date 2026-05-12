from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI

from doghouse import __version__
from doghouse.api.routes_services import router as services_router
from doghouse.common.config import load_config_from_env
from doghouse.common.paths import path_status


def create_app() -> FastAPI:
    app = FastAPI(title="Doghouse Watchdog v2", version=__version__)
    app.include_router(services_router)

    @app.get("/api/v1/status")
    def status() -> dict:
        config = load_config_from_env()
        return {
            "service": "doghouse",
            "version": __version__,
            "status": "ok",
            "mode": "report-only",
            "restart_enabled_default": config.safety.default_restart_enabled,
            "kill_enabled_default": config.safety.default_kill_enabled,
            "checked_at": datetime.now(UTC).isoformat(),
            "paths": path_status(config.paths),
        }

    return app
