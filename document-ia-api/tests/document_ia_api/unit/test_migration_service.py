from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from document_ia_api.infra.database.migration_service import MigrationService


@pytest.mark.asyncio
async def test_auto_migrate_analytics_with_custom_schema():
    service = MigrationService()

    mock_settings = MagicMock()
    mock_settings.is_configured.return_value = True
    mock_settings.POSTGRES_SCHEMA = "custom_analytics"
    mock_settings.get_database_url.return_value = "postgresql+asyncpg://user:pass@localhost:5432/db"

    mock_conn = AsyncMock()
    mock_engine = MagicMock()
    mock_engine.begin.return_value.__aenter__.return_value = mock_conn

    mock_manager = MagicMock()
    mock_manager.async_engine = mock_engine

    with (
        patch(
            "document_ia_api.infra.database.migration_service.analytics_database_settings",
            mock_settings,
        ),
        patch(
            "document_ia_api.infra.database.migration_service.get_analytics_database_manager",
            return_value=mock_manager,
        ),
        patch.object(service, "_run_migrations", new_callable=AsyncMock) as mock_run_migrations,
    ):
        await service.auto_migrate_analytics()

        # Check schema creation
        mock_conn.execute.assert_called_once()
        query_str = str(mock_conn.execute.call_args[0][0])
        assert 'CREATE SCHEMA IF NOT EXISTS "custom_analytics"' in query_str

        # Check migration execution with schema parameter
        mock_run_migrations.assert_called_once_with(
            db_url="postgresql+asyncpg://user:pass@localhost:5432/db",
            engine=mock_engine,
            label="(base analytics, schema: custom_analytics)",
            schema="custom_analytics",
        )


@pytest.mark.asyncio
async def test_auto_migrate_analytics_without_schema():
    service = MigrationService()

    mock_settings = MagicMock()
    mock_settings.is_configured.return_value = True
    mock_settings.POSTGRES_SCHEMA = None
    mock_settings.get_database_url.return_value = "postgresql+asyncpg://user:pass@localhost:5432/db"

    mock_engine = MagicMock()
    mock_manager = MagicMock()
    mock_manager.async_engine = mock_engine

    with (
        patch(
            "document_ia_api.infra.database.migration_service.analytics_database_settings",
            mock_settings,
        ),
        patch(
            "document_ia_api.infra.database.migration_service.get_analytics_database_manager",
            return_value=mock_manager,
        ),
        patch.object(service, "_run_migrations", new_callable=AsyncMock) as mock_run_migrations,
    ):
        await service.auto_migrate_analytics()

        # Check migration execution with schema=None
        mock_run_migrations.assert_called_once_with(
            db_url="postgresql+asyncpg://user:pass@localhost:5432/db",
            engine=mock_engine,
            label="(base analytics, schema: public)",
            schema=None,
        )
