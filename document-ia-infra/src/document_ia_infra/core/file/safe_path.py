"""Filesystem confinement utilities for Document IA."""

import logging
import os
from pathlib import Path
from uuid import UUID

from document_ia_infra.exception.security_exception import (
    InvalidUUIDException,
    PathTraversalException,
)

logger = logging.getLogger(__name__)

DEFAULT_SANDBOX_BASE = Path("/tmp/document_ia_worker.tmp")


def validate_execution_id(execution_id: str) -> UUID:
    """Validate that execution_id is a valid UUID string.

    Raises:
        InvalidUUIDException: If execution_id is not a valid UUID.
    """
    if not execution_id:
        raise InvalidUUIDException(f"Invalid execution_id: {execution_id!r} is empty")
    try:
        return UUID(execution_id.strip())
    except (ValueError, AttributeError) as exc:
        raise InvalidUUIDException(
            f"Invalid execution_id: {execution_id!r} is not a valid UUID"
        ) from exc


def get_execution_sandbox_root(
    execution_id: str,
    base_dir: Path | str = DEFAULT_SANDBOX_BASE,
) -> Path:
    """Return the canonical, confinement-verified sandbox root for an execution.

    Args:
        execution_id: UUID of the workflow execution.
        base_dir: Base directory for worker temp sandboxes.

    Returns:
        Canonical absolute Path to the execution sandbox directory.
    """
    valid_uuid = validate_execution_id(execution_id)
    base_path = Path(base_dir).resolve()
    sandbox_path = (base_path / str(valid_uuid)).resolve()

    if not sandbox_path.is_relative_to(base_path):
        raise PathTraversalException(
            f"Sandbox root {sandbox_path} escapes base directory {base_path}"
        )

    return sandbox_path


def validate_safe_path(
    target_path: Path | str,
    sandbox_root: Path | str,
) -> Path:
    """Canonicalize and verify that target_path remains strictly confined within sandbox_root.

    Raises:
        PathTraversalException: If target_path escapes sandbox_root or symlinks outside.
    """
    sandbox_root_resolved = Path(sandbox_root).resolve()
    target_raw = Path(target_path)

    if target_raw.is_absolute():
        resolved_target = target_raw.resolve()
    else:
        resolved_target = (sandbox_root_resolved / target_raw).resolve()

    if not resolved_target.is_relative_to(sandbox_root_resolved):
        raise PathTraversalException(
            f"Path traversal detected: {target_path} escapes sandbox {sandbox_root_resolved}"
        )

    return resolved_target


def safe_cleanup_directory(
    directory_path: Path | str,
    sandbox_root: Path | str | None = None,
) -> None:
    """Safely and recursively remove directory contents without following external symlinks.

    If a symlink is encountered inside the directory, the symlink itself is removed
    without touching the external target it points to.

    Args:
        directory_path: Path to the directory to clean up.
        sandbox_root: Optional sandbox boundary. If provided, directory_path must be confined.
    """
    raw_path = Path(directory_path)

    if sandbox_root is not None:
        resolved_dir = validate_safe_path(raw_path, sandbox_root)
    else:
        resolved_dir = raw_path.resolve()

    # If the directory target itself is a symlink, delete the symlink without following
    if raw_path.is_symlink():
        try:
            raw_path.unlink()
            logger.info("Removed symlink: %s", raw_path)
        except OSError as exc:
            logger.error("Failed to remove symlink %s: %s", raw_path, exc)
        return

    if not resolved_dir.exists():
        logger.debug("Directory does not exist for cleanup: %s", resolved_dir)
        return

    if not resolved_dir.is_dir():
        try:
            resolved_dir.unlink()
            logger.info("Deleted file: %s", resolved_dir)
        except OSError as exc:
            logger.error("Failed to delete file %s: %s", resolved_dir, exc)
        return

    # Bottom-up walk with followlinks=False to never traverse symlink targets
    for root, dirs, files in os.walk(
        str(resolved_dir), topdown=False, followlinks=False
    ):
        for fname in files:
            fpath = Path(root) / fname
            try:
                # unlink() removes the file or the symlink itself without following
                fpath.unlink()
                logger.debug("Deleted file/link: %s", fpath)
            except OSError as exc:
                logger.error("Failed to delete %s: %s", fpath, exc)

        for dname in dirs:
            dpath = Path(root) / dname
            try:
                if dpath.is_symlink():
                    dpath.unlink()
                    logger.debug("Deleted directory symlink: %s", dpath)
                else:
                    dpath.rmdir()
                    logger.debug("Removed directory: %s", dpath)
            except OSError as exc:
                logger.error("Failed to remove directory %s: %s", dpath, exc)

    # Finally, remove the top-level directory itself
    try:
        resolved_dir.rmdir()
        logger.info("Removed sandbox directory: %s", resolved_dir)
    except OSError as exc:
        logger.error("Failed to remove root directory %s: %s", resolved_dir, exc)
