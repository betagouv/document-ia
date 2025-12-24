"""Database connection and session management."""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import text
from sqlalchemy.orm import Session

from document_ia_evals.database.models import Base
from document_ia_infra.data.database import database_manager


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.

    Usage:
        with get_session() as session:
            session.add(experiment)
            session.commit()

    Yields:
        Session: A database session that will be automatically closed
    """
    with database_manager.sync_session_context() as session:
        yield session


def init_db():
    """Initialize the database (create tables if they don't exist)."""
    try:
        # Use a sync session to access the underlying bound engine/connection
        with database_manager.sync_session_context() as session:
            bind = session.get_bind()
            Base.metadata.create_all(bind=bind)
        return True
    except Exception as e:
        print(f"Failed to initialize database: {e}")
        return False


def test_db_connection() -> bool:
    """
    Test database connection.

    Returns:
        bool: True if connection successful, False otherwise
    """
    try:
        with database_manager.sync_session_context() as session:
            session.execute(text("SELECT 1"))
            session.commit()
        return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False
