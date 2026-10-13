"""Application factory; no database migration or model calls at startup."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from bidding_compliance import __version__
from bidding_compliance.core.config import Settings
from bidding_compliance.persistence.database import make_engine

from .documents import router as documents_router
from .errors import http_error_handler, validation_error_handler
from .middleware import RequestContextMiddleware
from .projects import router
from .schemas import HealthResponse
from .upload_limit import UploadBodyLimit


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if application.state.engine is not None:
                application.state.engine.dispose()

    app = FastAPI(
        title="招标文件智能合规审查 API",
        version=__version__,
        debug=False,
        docs_url="/docs" if configuration.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if configuration.docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = configuration
    app.state.engine = make_engine(configuration) if configuration.database_url else None
    app.include_router(router)
    app.include_router(documents_router)
    app.add_middleware(UploadBodyLimit)
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.get("/api/v1/health", response_model=HealthResponse, operation_id="getHealth")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    return app
