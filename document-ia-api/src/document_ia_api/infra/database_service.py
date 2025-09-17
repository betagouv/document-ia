import logging

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from document_ia_api.infra.database.database_connectivity_status import (
    DatabaseConnectivityStatus,
)
from document_ia_infra.data.database import database_manager

logger = logging.getLogger(__name__)


class DatabaseService:
    def __init__(self):
        pass

    async def check_database_connectivity(
        self, db: AsyncSession = Depends(database_manager.async_get_db)
    ) -> DatabaseConnectivityStatus:
        """
        Comprehensive database connectivity check.

        Performs basic connection test by executing a simple query.

        Returns:
            Dict containing connectivity status and details
        """
        connectivity_status = DatabaseConnectivityStatus.default()

        try:
            logger.info("Testing database connectivity...")
            result = await db.execute(text("SELECT 1"))
            result.scalar()

            connectivity_status.connected = True
            connectivity_status.is_healthy = True
            logger.info("Database connection established successfully")

        except SQLAlchemyError as e:
            error_msg = f"Database connection failed: {e}"
            connectivity_status.errors.append(error_msg)
            logger.error(error_msg)
            return connectivity_status

        except Exception as e:
            error_msg = f"Unexpected error during database connectivity check: {e}"
            connectivity_status.errors.append(error_msg)
            logger.error(error_msg)
            return connectivity_status

        return connectivity_status


database_service = DatabaseService()
