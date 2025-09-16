import os
import ssl
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class DatabaseSettings(BaseSettings):
    POSTGRES_DB: str | None = os.getenv("POSTGRES_DB")
    POSTGRES_HOST: str | None = os.getenv("POSTGRES_HOST")
    POSTGRES_PORT: int | None = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_SSL_MODE: str | None = os.getenv("POSTGRES_SSL_MODE")

    POSTGRES_USER: str | None = os.getenv("POSTGRES_USER")
    POSTGRES_PASSWORD: str | None = os.getenv("POSTGRES_PASSWORD")

    POSTGRESQL_URL: str | None = os.getenv("POSTGRESQL_URL")

    def _sanitize_postgresql_url(self, url: str, async_connection: bool = False) -> str:
        """Sanitize PostgreSQL URL by removing unsupported SSL parameters."""
        parsed = urlparse(url)

        # Remove query parameters that asyncpg doesn't support
        # asyncpg handles SSL through the ssl parameter, not URL parameters
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        # Convert postgres:// or postgresql:// to postgresql+asyncpg://
        clean_url = clean_url.replace("postgres://", "postgresql://")

        if async_connection:
            clean_url = clean_url.replace("postgresql://", "postgresql+asyncpg://")

        return clean_url

    def _create_postgresql_url(
        self,
        user: str,
        password: str,
        host: str,
        port: int,
        db: str,
        async_connection: bool = False,
    ) -> str:
        """Create PostgreSQL URL."""
        return self._sanitize_postgresql_url(
            f"postgresql://{user}:{password}@{host}:{port}/{db}", async_connection
        )

    # Build database URI from individual components or use POSTGRESQL_URL
    def get_database_url(self, async_connection: bool = False) -> str:
        # If POSTGRESQL_URL is provided, use it directly
        if self.POSTGRESQL_URL:
            return self._sanitize_postgresql_url(self.POSTGRESQL_URL, async_connection)

        # Fallback to individual components
        if not all(
            [
                self.POSTGRES_HOST is not None,
                self.POSTGRES_PORT is not None,
                self.POSTGRES_DB is not None,
                self.POSTGRES_USER is not None,
                self.POSTGRES_PASSWORD is not None,
            ]
        ):
            raise ValueError("Missing required PostgreSQL configuration")

        return self._create_postgresql_url(
            self.POSTGRES_USER or "",
            self.POSTGRES_PASSWORD or "",
            self.POSTGRES_HOST or "",
            self.POSTGRES_PORT or 5432,
            self.POSTGRES_DB or "",
            async_connection,
        )

    def get_ssl_context(self) -> ssl.SSLContext | None:
        """Get SSL context for database connections."""

        if self.POSTGRES_SSL_MODE in ["require", "prefer", "allow"]:
            ssl_context = ssl.create_default_context()
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            ssl_context.check_hostname = False
            return ssl_context

        return None


class S3Settings(BaseSettings):
    # S3/MinIO configuration
    S3_ENDPOINT_URL: str = os.getenv("S3_ENDPOINT_URL", "http://localhost:9000")
    S3_ACCESS_KEY_ID: str = os.getenv("S3_ACCESS_KEY_ID", "minioadmin")
    S3_SECRET_ACCESS_KEY: str = os.getenv("S3_SECRET_ACCESS_KEY", "minioadmin")
    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "document-ia")
    S3_REGION_NAME: str = os.getenv("S3_REGION_NAME", "us-east-1")
    S3_USE_SSL: bool = os.getenv("S3_USE_SSL", "false").lower() == "true"


class Settings(DatabaseSettings, S3Settings):
    # Application settings
    AUTO_MIGRATE: bool = os.getenv("AUTO_MIGRATE", "true").lower() == "true"

    # Rate limiting configuration
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = int(
        os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "300")
    )
    RATE_LIMIT_REQUESTS_PER_DAY: int = int(
        os.getenv("RATE_LIMIT_REQUESTS_PER_DAY", "5000")
    )


# Global settings instance
settings = Settings()
