"""Filesystem confinement utilities for Document IA."""

import errno
import logging
import os
from pathlib import Path
from typing import IO
from uuid import UUID

from document_ia_infra.exception.security_exception import (
    InvalidUUIDException,
    PathTraversalException,
)

logger = logging.getLogger(__name__)

DEFAULT_SANDBOX_BASE = Path("/tmp/document_ia_worker.tmp")

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class ConfinedDirectory:
    """A directory descriptor that file operations are anchored to.

    Checking a path and then acting on it is not a boundary: the path can be
    replaced with a symlink between the check and the `open`, and a later check
    then resolves the boundary through that same link and approves an external
    location. Anchoring on an open descriptor with `O_NOFOLLOW` removes the
    mutable pathname from the operation, so every file written or removed
    through this object stays in the directory that was validated here.
    """

    def __init__(self, fd: int, path: Path) -> None:
        self._fd = fd
        self.path = path

    def __enter__(self) -> "ConfinedDirectory":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def open_file(self, name: str, mode: str = "wb") -> IO[bytes]:
        """Open (creating) a file relative to this descriptor, never a symlink."""
        if "/" in name or name in (".", ".."):
            raise PathTraversalException(
                f"Refusing nested or relative name inside sandbox: {name!r}"
            )
        flags = os.O_WRONLY | os.O_CREAT | _O_NOFOLLOW | _O_CLOEXEC
        if "b" not in mode:
            flags |= os.O_BINARY if hasattr(os, "O_BINARY") else 0
        fd = os.open(name, flags, 0o600, dir_fd=self._fd)
        return os.fdopen(fd, mode)

    def replace(self, source_name: str, target_name: str) -> None:
        """Atomically rename within this directory."""
        for candidate in (source_name, target_name):
            if "/" in candidate or candidate in (".", ".."):
                raise PathTraversalException(
                    f"Refusing nested or relative name inside sandbox: {candidate!r}"
                )
        os.rename(
            source_name,
            target_name,
            src_dir_fd=self._fd,
            dst_dir_fd=self._fd,
        )

    def unlink(self, name: str) -> None:
        if "/" in name or name in (".", ".."):
            raise PathTraversalException(
                f"Refusing nested or relative name inside sandbox: {name!r}"
            )
        try:
            os.unlink(name, dir_fd=self._fd)
        except FileNotFoundError:
            pass


def open_confined_directory(
    directory_path: Path | str,
    sandbox_root: Path | str,
) -> ConfinedDirectory:
    """Validate `directory_path`, then hold a descriptor on it without following symlinks.

    Raises:
        PathTraversalException: if the directory escapes the sandbox, or if any
            component was replaced by a symlink.
    """
    resolved = validate_safe_path(directory_path, sandbox_root)
    try:
        fd = os.open(
            resolved,
            os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
        )
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise PathTraversalException(
                f"Sandbox directory {resolved} was replaced by a symlink"
            ) from exc
        raise

    # Re-check confinement on the descriptor we actually hold: if the parent was
    # swapped for a symlink, the resolved path and the real directory disagree.
    try:
        held = Path(os.readlink(f"/proc/self/fd/{fd}"))
    except OSError:
        held = resolved
    root_resolved = Path(sandbox_root).resolve()
    if not held.resolve().is_relative_to(root_resolved):
        os.close(fd)
        raise PathTraversalException(
            f"Sandbox directory {held} escapes sandbox {root_resolved}"
        )
    return ConfinedDirectory(fd, held)


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

    # If the directory target itself is a symlink, delete the symlink without following
    if raw_path.is_symlink():
        try:
            raw_path.unlink()
            logger.info("Removed symlink: %s", raw_path)
        except OSError as exc:
            logger.error("Failed to remove symlink %s: %s", raw_path, exc)
        return

    if sandbox_root is not None:
        # Anchor the walk on a descriptor: a boundary re-resolved per entry
        # would follow a directory that was swapped for a symlink after the
        # check, deleting files outside the sandbox.
        try:
            confined = open_confined_directory(raw_path, sandbox_root)
        except FileNotFoundError:
            logger.debug("Directory does not exist for cleanup: %s", raw_path)
            return
        resolved_dir = confined.path
    else:
        confined = None
        resolved_dir = raw_path.resolve()

    if not resolved_dir.exists():
        logger.debug("Directory does not exist for cleanup: %s", resolved_dir)
        if confined is not None:
            confined.close()
        return

    if not resolved_dir.is_dir():
        try:
            resolved_dir.unlink()
            logger.info("Deleted file: %s", resolved_dir)
        except OSError as exc:
            logger.error("Failed to delete file %s: %s", resolved_dir, exc)
        if confined is not None:
            confined.close()
        return

    # Bottom-up walk with followlinks=False to never traverse symlink targets
    try:
        _remove_tree_bottom_up(resolved_dir)
    finally:
        if confined is not None:
            confined.close()

    # Finally, remove the top-level directory itself
    try:
        resolved_dir.rmdir()
        logger.info("Removed sandbox directory: %s", resolved_dir)
    except OSError as exc:
        logger.error("Failed to remove root directory %s: %s", resolved_dir, exc)


def _remove_tree_bottom_up(resolved_dir: Path) -> None:
    """Delete the contents of an already-confined directory, never following links."""
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
