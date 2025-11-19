import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html
from starlette.staticfiles import StaticFiles

from api.routes import router
from document_ia_api.api.config import settings
from document_ia_api.api.exceptions.handler.exception_handlers import (
    setup_exception_handlers,
)
from document_ia_api.api.middleware.aggregator_middleware import (
    AggregationMiddleware,
    get_request_payload_safely,
)
from document_ia_api.api.middleware.rate_limiting_middleware import RateLimitMiddleware
from document_ia_api.api.middleware.request_id_middleware import RequestIDMiddleware
from document_ia_api.core.logging_setup import setup_logging
from document_ia_api.infra.database_service import database_service
from document_ia_infra.data.database import database_manager
from infra.database.migration_service import migration_service
from infra.redis_service import redis_service
from infra.s3_service import s3_service

MAX_BODY_BYTES = 2048

setup_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI application."""
    # Startup
    logger.info("Starting Document IA API...")

    # Check S3, Redis, and Database connectivity
    await s3_service.check_connectivity()
    await redis_service.check_connectivity()
    async with database_manager.local_session() as session:
        await database_service.check_database_connectivity(session)

    # Run database migrations
    await migration_service.auto_migrate()

    logger.info("Document IA API started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Document IA API...")


# Create FastAPI application
app = FastAPI(
    title="Document IA API",
    description="A powerful document processing API that enables automated document analysis, workflow execution, and intelligent document handling.",
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# app.mount("/static", StaticFiles(directory="static"), name="static")

# The last one added is the first one to be executed

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure according to your needs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Add rate limiting middleware
app.add_middleware(RateLimitMiddleware)

app.add_middleware(AggregationMiddleware)
app.add_middleware(RequestIDMiddleware)

setup_exception_handlers(app)


@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(
        openapi_url=app.openapi_url or "",
        title=app.title + " - ReDoc",
        redoc_js_url="/static/redoc.standalone.js",
    )


# Include API routes
# We use a dependency here to ensure the request body is read
# It's used to populate the request for the aggregated logger.
# We can not do that inside a middleware as the body can be read only once.
app.include_router(
    router, prefix="/api", dependencies=[Depends(get_request_payload_safely)]
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(  # type: ignore
        "main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=True,
        log_config=None,
    )
