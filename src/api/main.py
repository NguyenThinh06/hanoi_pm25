"""Run with: python -m uvicorn src.api.main:app --reload."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings
from .database import Database
from .errors import install_error_handlers
from .routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(settings)
        app.state.database = database
        try:
            database.open()
            yield
        finally:
            database.close()

    app = FastAPI(
        title="Hanoi PM2.5 API",
        version="1.0.0",
        lifespan=lifespan,
        description="Ước tính hồi cứu và quan trắc PM2.5 (µg/m³). API Contract v1 trong docs/HANDOVER.md.",
    )
    install_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET"],
            allow_headers=["Accept", "Content-Type"],
        )
    app.include_router(router)
    return app


app = create_app()
