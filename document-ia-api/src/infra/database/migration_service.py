import logging
import subprocess
import sys
from typing import Dict, Any, Optional
from pathlib import Path

from infra.config import settings

# Configure logging
logger = logging.getLogger(__name__)


class MigrationStatus:
    """Represents the current migration status."""

    def __init__(
        self,
        current_revision: Optional[str],
        head_revision: Optional[str],
        is_up_to_date: bool,
    ):
        self.current_revision = current_revision
        self.head_revision = head_revision
        self.is_up_to_date = is_up_to_date


class MigrationResult:
    """Represents the result of a migration operation."""

    def __init__(self, success: bool, message: str, migrations_applied: int = 0):
        self.success = success
        self.message = message
        self.migrations_applied = migrations_applied


class MigrationService:
    """Service for handling database migrations using Alembic."""

    def __init__(self):
        self.alembic_ini_path = (
            Path(__file__).parent.parent.parent.parent / "alembic.ini"
        )
        self.alembic_script_location = (
            Path(__file__).parent.parent.parent.parent / "document-ia-api" / "alembic"
        )

    async def auto_migrate(self):
        """
        Auto-migrate the database.

        Returns:
            MigrationResult: Result of the migration operation
        """
        # Run database migrations after connectivity checks
        if settings.AUTO_MIGRATE:
            logger.info("Running database migrations...")
            migration_result = await self.run_migrations()
            if not migration_result.success:
                logger.error(f"Migration failed: {migration_result.message}")
                raise RuntimeError(
                    f"Database migration failed: {migration_result.message}"
                )
            else:
                logger.info(f"Migration completed: {migration_result.message}")
        else:
            logger.info("Auto-migration disabled, skipping database migrations")

    async def check_migration_status(self) -> MigrationStatus:
        """
        Check the current migration status.

        Returns:
            MigrationStatus: Current migration status information
        """
        try:
            logger.info("Checking migration status...")

            # Get current revision
            current_revision = await self._get_current_revision()

            # Get head revision
            head_revision = await self._get_head_revision()

            # Check if migrations are up to date
            is_up_to_date = current_revision == head_revision

            logger.info(
                f"Migration status - Current: {current_revision}, Head: {head_revision}, Up to date: {is_up_to_date}"
            )

            return MigrationStatus(
                current_revision=current_revision,
                head_revision=head_revision,
                is_up_to_date=is_up_to_date,
            )

        except Exception as e:
            logger.error(f"Failed to check migration status: {e}")
            raise

    async def is_migration_needed(self) -> bool:
        """
        Check if migrations are needed.

        Returns:
            bool: True if migrations are needed, False otherwise
        """
        try:
            status = await self.check_migration_status()
            return not status.is_up_to_date
        except Exception as e:
            logger.error(f"Failed to check if migration is needed: {e}")
            return True  # Assume migration is needed if we can't check

    async def run_migrations(self) -> MigrationResult:
        """
        Run database migrations.

        Returns:
            MigrationResult: Result of the migration operation
        """
        try:
            logger.info("Starting database migrations...")

            # Check if migrations are needed first
            if not await self.is_migration_needed():
                logger.info("Database is already up to date, no migrations needed")
                return MigrationResult(
                    success=True,
                    message="Database is already up to date",
                    migrations_applied=0,
                )

            # Run migrations
            result = await self._run_alembic_upgrade()

            if result["success"]:
                logger.info(
                    f"Database migrations completed successfully: {result['message']}"
                )
                return MigrationResult(
                    success=True,
                    message=result["message"],
                    migrations_applied=result.get("migrations_applied", 0),
                )
            else:
                logger.error(f"Database migrations failed: {result['message']}")
                return MigrationResult(success=False, message=result["message"])

        except Exception as e:
            error_msg = f"Unexpected error during migration: {e}"
            logger.error(error_msg)
            return MigrationResult(success=False, message=error_msg)

    async def _get_current_revision(self) -> Optional[str]:
        """Get the current database revision."""
        try:
            result = await self._run_alembic_command(["current"])
            if result["success"] and result["output"]:
                # Extract revision from output (format: "Current revision for postgresql://... is abc123")
                lines = result["output"].strip().split("\n")
                for line in lines:
                    if "Current revision" in line and "is" in line:
                        parts = line.split("is")
                        if len(parts) > 1:
                            return parts[1].strip()
                return None
            return None
        except Exception as e:
            logger.error(f"Failed to get current revision: {e}")
            return None

    async def _get_head_revision(self) -> Optional[str]:
        """Get the head revision."""
        try:
            result = await self._run_alembic_command(["heads"])
            if result["success"] and result["output"]:
                # Extract revision from output (format: "abc123 (head)")
                lines = result["output"].strip().split("\n")
                for line in lines:
                    if "(head)" in line:
                        return line.split()[0]
                return None
            return None
        except Exception as e:
            logger.error(f"Failed to get head revision: {e}")
            return None

    async def _run_alembic_upgrade(self) -> Dict[str, Any]:
        """Run alembic upgrade command."""
        return await self._run_alembic_command(["upgrade", "head"])

    async def _run_alembic_command(self, command: list) -> Dict[str, Any]:
        """
        Run an alembic command.

        Args:
            command: List of command arguments

        Returns:
            Dict containing success status, output, and error
        """
        try:
            # Build the full command
            full_command = [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(self.alembic_ini_path),
            ] + command

            logger.debug(f"Running command: {' '.join(full_command)}")

            # Run the command
            process = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                cwd=str(self.alembic_ini_path.parent),
            )

            if process.returncode == 0:
                return {
                    "success": True,
                    "output": process.stdout,
                    "error": process.stderr,
                }
            else:
                return {
                    "success": False,
                    "output": process.stdout,
                    "error": process.stderr,
                    "return_code": process.returncode,
                }

        except Exception as e:
            return {"success": False, "output": "", "error": str(e), "return_code": -1}


# Global migration service instance
migration_service = MigrationService()
