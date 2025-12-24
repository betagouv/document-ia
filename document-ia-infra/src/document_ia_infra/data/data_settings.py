import ssl
from urllib.parse import urlparse

from pydantic import Field, SecretStr

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class DatabaseSettings(BaseDocumentIaSettings):
    POSTGRES_DB: str | None = Field(default=None)
    POSTGRES_HOST: str | None = Field(default=None)
    POSTGRES_PORT: int = Field(default=5432)
    POSTGRES_SSL_MODE: str | None = Field(default=None)

    POSTGRES_USER: str | None = Field(default=None)
    POSTGRES_PASSWORD: SecretStr | None = Field(default=None)

    POSTGRESQL_URL: str | None = Field(default=None)

    WEBHOOK_SECRET_ENCRYPTION_KEY: SecretStr | None = Field(default=None)

    DB_POOL_SIZE: int = Field(default=5)
    DB_MAX_OVERFLOW: int = Field(default=10)
    DB_POOL_TIMEOUT: int = Field(default=30)  # seconds to wait
    DB_POOL_RECYCLE: int = Field(default=1800)  # seconds to recycle
    DB_POOL_PRE_PING: bool = Field(default=True)

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
                self.POSTGRES_DB is not None,
                self.POSTGRES_USER is not None,
                self.POSTGRES_PASSWORD is not None,
            ]
        ):
            raise ValueError("Missing required PostgreSQL configuration")

        assert self.POSTGRES_PASSWORD is not None
        password = self.POSTGRES_PASSWORD.get_secret_value()

        return self._create_postgresql_url(
            self.POSTGRES_USER or "",
            password,
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


database_settings = DatabaseSettings()
