import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.routes import router
from api.rate_limiting import RateLimitMiddleware
from infra.s3_service import s3_service

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI application."""
    # Startup
    logger.info("Starting Document IA API...")

    # Check S3 connectivity
    await s3_service.check_connectivity()

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
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

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

# Include API routes
app.include_router(router, prefix="/api")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app", host=settings.SERVER_HOST, port=settings.SERVER_PORT, reload=True
    )
