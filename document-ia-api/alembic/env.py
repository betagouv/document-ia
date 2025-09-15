from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from infra.config import settings
from infra.database.database import Base

target_metadata = Base.metadata

config = context.config
if config.config_file_name is not None and not config.attributes.get(
    "skip_file_config", False
):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def get_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url is None:
        # Used with cli execution
        url = settings.get_database_url(async_connection=True)
    return url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = config.attributes.get("connection", None)
    if connectable is not None:
        async with connectable:
            await connectable.run_sync(do_run_migrations)
    else:
        # If no connection is provided in config, we create one
        connectable = create_async_engine(
            get_url(),
            poolclass=pool.NullPool,
            future=True,
        )
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await connectable.dispose()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        transaction_per_migration=True,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run():
    """
    Point d’entrée utilisé par alembic.command.* ; détermine offline/online.
    """
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        import asyncio

        asyncio.run(run_migrations_online())


run()
