"""Database connection and session management."""

from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool

from document_ia_evals.database.models import Base
from document_ia_infra.data.data_settings import database_settings


class DatabaseManager:
    """
    Singleton database connection manager.

    Handles database connections, session creation, and connection pooling.
    """

    _instance: Optional["DatabaseManager"] = None
    _engine: Optional[Engine] = None
    _session_factory: Optional[sessionmaker] = None

    def __new__(cls):
        """Ensure only one instance exists (Singleton pattern)."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the database manager (only once)."""
        if self._engine is None:
            self._initialize_engine()

    def _initialize_engine(self):
        """Create the database engine with connection pooling."""
        # Get database URL from environment

        # For Streamlit, we use NullPool to avoid connection pool issues
        # Each request gets a fresh connection
        self._engine = create_engine(
            database_settings.get_database_url(),
            poolclass=NullPool,  # No connection pooling for Streamlit
            echo=False,  # Set to True for SQL debugging
            future=True  # Use SQLAlchemy 2.0 style
        )

        # Create session factory
        self._session_factory = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False  # Don't expire objects after commit
        )

    @property
    def engine(self) -> Engine:
        """Get the database engine."""
        if self._engine is None:
            self._initialize_engine()
        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        """Get the session factory."""
        if self._session_factory is None:
            self._initialize_engine()
        return self._session_factory

    def create_tables(self):
        """Create all tables in the database."""
        Base.metadata.create_all(self.engine)

    def drop_tables(self):
        """Drop all tables from the database (use with caution!)."""
        Base.metadata.drop_all(self.engine)

    def test_connection(self) -> bool:
        """
        Test database connectivity.

        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.commit()
            return True
        except Exception as e:
            print(f"Database connection failed: {e}")
            return False

    def get_session(self) -> Session:
        """
        Create a new database session.

        Returns:
            Session: A new SQLAlchemy session
        """
        return self.session_factory()

    def close(self):
        """Close the database engine and cleanup."""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None


# Global database manager instance
db_manager = DatabaseManager()


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
    session = db_manager.get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    """Initialize the database (create tables if they don't exist)."""
    try:
        db_manager.create_tables()
        return True
    except Exception as e:
        print(f"Failed to initialize database: {e}")
        return False


def test_db_connection() -> bool:
    """Test database connection."""
    return db_manager.test_connection()
