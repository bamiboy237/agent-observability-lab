from fastapi import FastAPI

from app.api.health_router import router as health_router
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Agent Observability Lab")
    app.state.settings = settings
    app.include_router(health_router)
    return app
