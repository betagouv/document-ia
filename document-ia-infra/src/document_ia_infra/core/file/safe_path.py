"""Filesystem confinement utilities for Document IA."""

import errno
import stat
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
    # The boundary must be a real directory, not a path that resolves somewhere
    # else. Resolving it would silently adopt the attacker's target, and every
    # later comparison would then be relative to that same wrong place.
    root_path = Path(sandbox_root)
    if root_path.is_symlink():
        raise PathTraversalException(
            f"Sandbox root {root_path} was replaced by a symlink"
        )
    root_resolved = root_path.resolve()
    resolved = validate_safe_path(directory_path, root_resolved)
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

    # Re-check confinement on the descriptor actually held, against the boundary
    # captured before the open: a parent swapped in between then disagrees.
    try:
        held = Path(os.readlink(f"/proc/self/fd/{fd}"))
    except OSError:
        held = resolved
    if not held.is_relative_to(root_resolved):
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


def _remove_tree_relative(dir_fd: int) -> None:
    """Delete a directory's contents relative to an open descriptor.

    Every step is descriptor-relative with `O_NOFOLLOW`, so a child swapped for a
    symlink is removed as a link and never traversed. Nothing here resolves a
    pathname, which is what a walk-based implementation would do.
    """
    try:
        entries = os.listdir(dir_fd)
    except OSError as exc:
        logger.error("Failed to list directory for cleanup: %s", exc)
        return

    for name in entries:
        try:
            stat_result = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except OSError as exc:
            logger.error("Failed to inspect %s during cleanup: %s", name, exc)
            continue

        if stat.S_ISDIR(stat_result.st_mode):
            child_fd = -1
            try:
                child_fd = os.open(
                    name,
                    os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
                    dir_fd=dir_fd,
                )
            except OSError as exc:
                # A directory replaced by a symlink is unlinked, never entered.
                logger.info("Removing non-directory entry %s: %s", name, exc)
                try:
                    os.unlink(name, dir_fd=dir_fd)
                except OSError as unlink_exc:
                    logger.error("Failed to unlink %s: %s", name, unlink_exc)
                continue
            try:
                _remove_tree_relative(child_fd)
                os.rmdir(name, dir_fd=dir_fd)
            except OSError as exc:
                logger.error("Failed to remove directory %s: %s", name, exc)
            finally:
                os.close(child_fd)
            continue

        try:
            os.unlink(name, dir_fd=dir_fd)
            logger.debug("Deleted file/link: %s", name)
        except OSError as exc:
            logger.error("Failed to delete %s: %s", name, exc)


def safe_cleanup_directory(
    directory_path: Path | str,
    sandbox_root: Path | str | None = None,
) -> None:
    """Safely and recursively remove directory contents without following external symlinks.

    If a symlink is encountered inside the directory, the symlink itself is removed
    without touching the external target it points to. Deletion is descriptor
    relative throughout: deleting via pathnames would let a directory swapped
    after validation redirect the walk outside the sandbox.

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

    # Open the target itself with no-follow semantics, then work only through
    # descriptors. The confinement re-check happens on the descriptor held.
    try:
        confined = open_confined_directory(
            raw_path, sandbox_root if sandbox_root is not None else raw_path.parent
        )
    except FileNotFoundError:
        logger.debug("Directory does not exist for cleanup: %s", raw_path)
        return
    except NotADirectoryError:
        try:
            raw_path.unlink()
            logger.info("Deleted file: %s", raw_path)
        except OSError as exc:
            logger.error("Failed to delete file %s: %s", raw_path, exc)
        return
    except PathTraversalException as exc:
        logger.error("Refusing to clean up %s: %s", raw_path, exc)
        return

    parent_fd = -1
    try:
        _remove_tree_relative(confined._fd)
        # Remove the directory itself through its parent, still no-follow.
        parent_fd = os.open(
            os.path.dirname(confined.path) or ".",
            os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC,
        )
        os.rmdir(os.path.basename(confined.path), dir_fd=parent_fd)
        logger.info("Removed sandbox directory: %s", confined.path)
    except OSError as exc:
        logger.error("Failed to remove %s: %s", confined.path, exc)
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)
        confined.close()
