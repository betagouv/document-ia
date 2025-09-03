from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from infra.config import settings


class Base(DeclarativeBase):
    pass


# Build database URI from individual components
def build_database_uri() -> str:
    """Build PostgreSQL URI from individual components."""
    if not all(
        [
            settings.POSTGRES_HOST,
            settings.POSTGRES_PORT,
            settings.POSTGRES_DB,
            settings.POSTGRES_USER,
            settings.POSTGRES_PASSWORD,
        ]
    ):
        raise ValueError("Missing required PostgreSQL configuration")

    return (
        f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )


async_engine = create_async_engine(build_database_uri(), echo=False, future=True)

local_session = async_sessionmaker(
    bind=async_engine, class_=AsyncSession, expire_on_commit=False
)


async def async_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with local_session() as db:
        yield db
