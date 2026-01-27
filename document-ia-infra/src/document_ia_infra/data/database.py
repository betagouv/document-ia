import logging
from collections.abc import AsyncGenerator
from contextlib import contextmanager
from typing import Dict, Any, Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from sqlalchemy.pool import NullPool

from document_ia_infra.data.data_settings import database_settings as settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class DatabaseManager:
    def __init__(
        self,
        *,
        pool_size: int = settings.DB_POOL_SIZE,
        max_overflow: int = settings.DB_MAX_OVERFLOW,
        pool_timeout: int = settings.DB_POOL_TIMEOUT,
        pool_recycle: int = settings.DB_POOL_RECYCLE,
        pool_pre_ping: bool = settings.DB_POOL_PRE_PING,
    ):
        self.engine_kwargs: Dict[str, Any] = {
            "echo": False,
            "future": True,
        }

        self.ssl_context = settings.get_ssl_context()
        if self.ssl_context:
            self.engine_kwargs["connect_args"] = {"ssl": self.ssl_context}

        self.async_engine = create_async_engine(
            settings.get_database_url(async_connection=True),
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            pool_pre_ping=pool_pre_ping,
            **self.engine_kwargs,
        )

        # Session factory for async usage (API/worker)
        self.local_session = async_sessionmaker(
            bind=self.async_engine, class_=AsyncSession, expire_on_commit=False
        )

        # Lazy sync engine/session for Streamlit/scripts only
        self._sync_engine: Optional[Any] = None
        self._sync_session_factory: Optional[sessionmaker[Session]] = None

    async def async_get_db(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.local_session() as db:
            yield db

    # --- Sync helpers (lazy init) ---
    def _ensure_sync_engine(self) -> None:
        if self._sync_engine is not None and self._sync_session_factory is not None:
            return
        sync_engine_kwargs = {**self.engine_kwargs}
        # NullPool to avoid holding connections in sync contexts
        sync_engine_kwargs["poolclass"] = NullPool
        self._sync_engine = create_engine(
            settings.get_database_url(async_connection=False), **sync_engine_kwargs
        )
        self._sync_session_factory = sessionmaker(
            bind=self._sync_engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )

    def get_sync_session(self) -> Session:
        self._ensure_sync_engine()
        assert self._sync_session_factory is not None
        return self._sync_session_factory()

    @contextmanager
    def sync_session_context(self) -> Generator[Session, None, None]:
        self._ensure_sync_engine()
        assert self._sync_session_factory is not None
        session = self._sync_session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def dispose_async(self) -> None:
        try:
            await self.async_engine.dispose()
        finally:
            try:
                if self._sync_engine is not None:
                    self._sync_engine.dispose()
            except Exception:
                pass


database_manager = DatabaseManager()
