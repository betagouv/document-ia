from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.routes import router

# Create FastAPI application
app = FastAPI(
    title="API Document IA",
    description="API permettant de lancer et gérer des workflows d'analyse de documents",
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure according to your needs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api", tags=["API"])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app", host=settings.SERVER_HOST, port=settings.SERVER_PORT, reload=True
    )
