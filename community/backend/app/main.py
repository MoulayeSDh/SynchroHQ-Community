from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.core.logging import configure_logging
from app.modules.analytics.routes import router as analytics_router
from app.modules.forms.routes import router as forms_router
from app.modules.geospatial.routes import router as geospatial_router
from app.modules.hierarchy.routes import router as hierarchy_router
from app.modules.identity.routes import router as identity_router
from app.modules.identity.session import router as session_router
from app.modules.reports.routes import router as reports_router
from app.modules.sync.routes import router as sync_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.app_env == "production" and (
        len(settings.auth_jwt_secret) < 32
        or settings.auth_jwt_secret == "development-only-change-me-32-chars"
    ):
        raise RuntimeError("Production requires a unique AUTH_JWT_SECRET of at least 32 characters")
    configure_logging(settings.log_level)
    application = FastAPI(title=settings.app_name, lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(identity_router)
    application.include_router(session_router)
    application.include_router(forms_router)
    application.include_router(sync_router)
    application.include_router(hierarchy_router)
    application.include_router(analytics_router)
    application.include_router(geospatial_router)
    application.include_router(reports_router)

    @application.get("/api/health", tags=["system"])
    def health() -> dict[str, str]:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    return application


app = create_app()
