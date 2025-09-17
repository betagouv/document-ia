import logging
from collections.abc import AsyncGenerator
from typing import Dict, Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from document_ia_infra.data.data_settings import database_settings as settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class DatabaseManager:
    def __init__(self):
        # Create async engine with SSL context for Heroku compatibility
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

        self.local_session = async_sessionmaker(
            bind=self.async_engine, class_=AsyncSession, expire_on_commit=False
        )

    async def async_get_db(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.local_session() as db:
            yield db


database_manager = DatabaseManager()
