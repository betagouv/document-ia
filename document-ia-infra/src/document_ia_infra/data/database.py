import logging
from collections.abc import AsyncGenerator
from contextlib import contextmanager
from typing import Dict, Any, Generator

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
    def __init__(self):
        self.engine_kwargs: Dict[str, Any] = {
            "echo": False,
            "future": True,
        }

        self.ssl_context = settings.get_ssl_context()
        if self.ssl_context:
            self.engine_kwargs["connect_args"] = {"ssl": self.ssl_context}

        self.async_engine = create_async_engine(
            settings.get_database_url(async_connection=True), **self.engine_kwargs
        )

        # Sync engine for evals/Streamlit (using NullPool to avoid connection pool issues)
        sync_engine_kwargs = {**self.engine_kwargs}
        sync_engine_kwargs["poolclass"] = NullPool
        self.sync_engine = create_engine(
            settings.get_database_url(async_connection=False), **sync_engine_kwargs
        )

        self.local_session = async_sessionmaker(
            bind=self.async_engine, class_=AsyncSession, expire_on_commit=False
        )

        self.sync_session_factory = sessionmaker(
            bind=self.sync_engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False
        )

    async def async_get_db(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.local_session() as db:
            yield db

    def get_sync_session(self) -> Session:
        return self.sync_session_factory()

    @contextmanager
    def sync_session_context(self) -> Generator[Session, None, None]:
        session = self.get_sync_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


database_manager = DatabaseManager()
