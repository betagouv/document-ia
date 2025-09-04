import logging
from collections.abc import AsyncGenerator
from typing import Dict, Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text

from infra.config import settings

# Configure logging
logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


async_engine = create_async_engine(
    settings.get_database_url(async_connection=True), echo=False, future=True
)

local_session = async_sessionmaker(
    bind=async_engine, class_=AsyncSession, expire_on_commit=False
)


async def async_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with local_session() as db:
        yield db


async def check_database_connectivity() -> Dict[str, Any]:
    """
    Comprehensive database connectivity check.

    Performs basic connection test by executing a simple query.

    Returns:
        Dict containing connectivity status and details
    """
    connectivity_status = {
        "connected": False,
        "is_healthy": False,
        "errors": [],
    }

    try:
        logger.info("Testing database connectivity...")

        # Test connection by executing a simple query
        async with local_session() as session:
            # Execute a simple query to test connectivity
            result = await session.execute(text("SELECT 1"))
            result.scalar()

        connectivity_status["connected"] = True
        connectivity_status["is_healthy"] = True
        logger.info("Database connection established successfully")

    except SQLAlchemyError as e:
        error_msg = f"Database connection failed: {e}"
        connectivity_status["errors"].append(error_msg)
        logger.error(error_msg)
        return connectivity_status

    except Exception as e:
        error_msg = f"Unexpected error during database connectivity check: {e}"
        connectivity_status["errors"].append(error_msg)
        logger.error(error_msg)
        return connectivity_status

    return connectivity_status
