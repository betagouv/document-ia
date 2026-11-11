"""Filesystem confinement utilities for Document IA."""

import errno
import fcntl
import logging
import os
import stat
from pathlib import Path
from typing import IO
from uuid import UUID

from document_ia_infra.exception.security_exception import (
    InvalidUUIDException,
    PathTraversalException,
)

logger = logging.getLogger(__name__)

DEFAULT_SANDBOX_BASE = Path("/tmp/document_ia_worker.tmp")

_O_NOFOLLOW: int = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY: int = getattr(os, "O_DIRECTORY", 0)
_O_CLOEXEC: int = getattr(os, "O_CLOEXEC", 0)
_O_BINARY: int = getattr(os, "O_BINARY", 0)


def _fd_to_path(fd: int) -> Path | None:
    """Resolve the real filesystem path for an open file descriptor.

    Supports Linux (/proc/self/fd) and macOS (fcntl F_GETPATH).
    """
    # On Linux:
    try:
        return Path(os.readlink(f"/proc/self/fd/{fd}"))
    except OSError:
        pass

    # On macOS (Darwin):
    if hasattr(fcntl, "F_GETPATH"):
        try:
            buf = b"\0" * 1024
            res = fcntl.fcntl(fd, fcntl.F_GETPATH, buf)
            return Path(res.rstrip(b"\0").decode("utf-8", errors="surrogateescape"))
        except OSError:
            pass

    return None


def ensure_directory_permissions(path: Path | str, mode: int = 0o700) -> Path:
    """Ensure directory exists and has strict permissions, rejecting symlinks.

    Creates the directory with mode if it does not exist, and explicitly calls
    os.fchmod to override any restrictive or permissive system umask.

    Args:
        path: Directory path to create/verify.
        mode: Octal permission mode (defaults to 0o700: rwx------).

    Returns:
        Path object pointing to the secured directory.

    Raises:
        PathTraversalException: If path is a symlink or was replaced by one.
    """
    target = Path(path)
    if target.is_symlink():
        raise PathTraversalException(
            f"Directory {target} is a symlink; refusing to use it"
        )
    target.mkdir(parents=True, exist_ok=True, mode=mode)
    try:
        fd = os.open(target, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC)
        try:
            os.fchmod(fd, mode)
        finally:
            os.close(fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise PathTraversalException(
                f"Directory {target} was replaced by a symlink"
            ) from exc
        logger.warning(
            "Failed to set permissions %o on directory %s: %s", mode, target, exc
        )
    return target


def ensure_file_permissions(path: Path | str, mode: int = 0o600) -> Path:
    """Ensure file has strict permissions, rejecting symlinks.

    Args:
        path: File path to verify.
        mode: Octal permission mode (defaults to 0o600: rw-------).

    Returns:
        Path object pointing to the secured file.

    Raises:
        PathTraversalException: If path is a symlink or was replaced by one.
    """
    target = Path(path)
    if target.is_symlink():
        raise PathTraversalException(f"File {target} is a symlink; refusing to use it")
    try:
        fd = os.open(target, os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC)
        try:
            os.fchmod(fd, mode)
        finally:
            os.close(fd)
    except FileNotFoundError:
        pass
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise PathTraversalException(
                f"File {target} was replaced by a symlink"
            ) from exc
        logger.warning("Failed to set permissions %o on file %s: %s", mode, target, exc)
    return target


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

    @property
    def fd(self) -> int:
        """File descriptor held by this confined directory."""
        return self._fd

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
        flags: int = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_NOFOLLOW | _O_CLOEXEC
        if "b" in mode:
            flags |= _O_BINARY
        fd = os.open(name, flags, 0o600, dir_fd=self._fd)
        try:
            os.fchmod(fd, 0o600)
            return os.fdopen(fd, mode)
        except Exception:
            os.close(fd)
            raise

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
    root_path = Path(sandbox_root)
    if root_path.is_symlink():
        raise PathTraversalException(
            f"Sandbox root {root_path} is a symlink; refusing to use it"
        )
    root_lexical = Path(os.path.normpath(root_path.absolute()))
    resolved = validate_safe_path(directory_path, root_lexical)

    try:
        root_fd = os.open(
            root_lexical,
            os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
        )
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise PathTraversalException(
                f"Sandbox root {root_lexical} was replaced by a symlink"
            ) from exc
        raise

    try:
        root_held = _fd_to_path(root_fd) or root_lexical
        rel_parts = resolved.relative_to(root_lexical).parts
        if not rel_parts:
            fd = os.dup(root_fd)
        else:
            curr_fd = os.dup(root_fd)
            try:
                for part in rel_parts:
                    next_fd = os.open(
                        part,
                        os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC,
                        dir_fd=curr_fd,
                    )
                    os.close(curr_fd)
                    curr_fd = next_fd
                fd = curr_fd
            except OSError as exc:
                os.close(curr_fd)
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise PathTraversalException(
                        f"Sandbox directory {resolved} was replaced by a symlink"
                    ) from exc
                raise
    finally:
        os.close(root_fd)

    held = _fd_to_path(fd) or resolved
    if not held.is_relative_to(root_held):
        os.close(fd)
        raise PathTraversalException(
            f"Sandbox directory {held} escapes sandbox {root_held}"
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

    Ensures that base_dir and the execution directory have strict 0o700 permissions.

    Args:
        execution_id: UUID of the workflow execution.
        base_dir: Base directory for worker temp sandboxes.

    Returns:
        Canonical absolute Path to the execution sandbox directory.
    """
    valid_uuid = validate_execution_id(execution_id)
    raw_base = Path(base_dir)
    if raw_base.is_symlink():
        raise PathTraversalException(
            f"Sandbox base {raw_base} is a symlink; refusing to use it"
        )
    base_path = raw_base.resolve()

    ensure_directory_permissions(base_path, 0o700)

    # The boundary is `<base>/<execution_id>` by construction, never a value
    # derived from the filesystem. Canonicalising the entry would adopt whatever
    # a symlink points at — a link to the shared base passes `is_relative_to` and
    # makes this execution's cleanup delete other executions' files. Checking
    # `is_symlink()` first and resolving afterwards is still a race, because the
    # two are separate operations on a mutable path; the path is therefore never
    # canonicalised at all.
    execution_dir = base_path / str(valid_uuid)

    # Reject a symlinked entry when it is observable. This is not the guarantee —
    # the operations that touch the directory open it with O_NOFOLLOW — but it
    # fails early and legibly for the common case.
    if execution_dir.is_symlink():
        raise PathTraversalException(
            f"Execution sandbox {execution_dir} is a symlink; refusing to use it"
        )

    return execution_dir


def validate_safe_path(
    target_path: Path | str,
    sandbox_root: Path | str,
) -> Path:
    """Verify lexically that target_path stays confined within sandbox_root.

    The comparison is deliberately lexical, not resolved: resolving both sides
    makes them move together when a component is replaced by a symlink, so the
    check passes against the attacker's directory. This is a cheap, legible
    pre-check for `..` segments and absolute escapes; the binding guarantee is
    the `O_NOFOLLOW` open plus the descriptor comparison in
    `open_confined_directory`.

    Raises:
        PathTraversalException: If target_path escapes sandbox_root lexically.
    """
    sandbox_root_resolved = Path(os.path.normpath(Path(sandbox_root).absolute()))
    target_raw = Path(target_path)

    if target_raw.is_absolute():
        normalized_target = Path(os.path.normpath(target_raw))
    else:
        normalized_target = Path(os.path.normpath(sandbox_root_resolved / target_raw))

    if not normalized_target.is_relative_to(sandbox_root_resolved):
        raise PathTraversalException(
            f"Path traversal detected: {target_path} escapes sandbox {sandbox_root_resolved}"
        )

    return normalized_target


def _remove_tree_relative(dir_fd: int) -> bool:
    """Delete a directory's contents relative to an open descriptor.

    Every step is descriptor-relative with `O_NOFOLLOW`, so a child swapped for a
    symlink is removed as a link and never traversed. Nothing here resolves a
    pathname, which is what a walk-based implementation would do.

    Returns:
        True if all entries were successfully removed, False otherwise.
    """
    try:
        entries = os.listdir(dir_fd)
    except OSError as exc:
        logger.error("Failed to list directory for cleanup: %s", exc)
        return False

    all_success = True
    for name in entries:
        try:
            stat_result = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except OSError as exc:
            logger.error("Failed to inspect %s during cleanup: %s", name, exc)
            all_success = False
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
                    all_success = False
                continue
            try:
                child_ok = _remove_tree_relative(child_fd)
                if not child_ok:
                    all_success = False
                os.rmdir(name, dir_fd=dir_fd)
            except OSError as exc:
                logger.error("Failed to remove directory %s: %s", name, exc)
                all_success = False
            finally:
                os.close(child_fd)
            continue

        try:
            os.unlink(name, dir_fd=dir_fd)
            logger.debug("Deleted file/link: %s", name)
        except OSError as exc:
            logger.error("Failed to delete %s: %s", name, exc)
            all_success = False

    return all_success


def safe_cleanup_directory(
    directory_path: Path | str,
    sandbox_root: Path | str | None = None,
) -> bool:
    """Safely and recursively remove directory contents without following external symlinks.

    If a symlink is encountered inside the directory, the symlink itself is removed
    without touching the external target it points to. Deletion is descriptor
    relative throughout: deleting via pathnames would let a directory swapped
    after validation redirect the walk outside the sandbox.

    If directory removal fails with an OSError, a WARNING is logged without blocking
    the worker thread; recovery is deferred to the background sweeper.

    Args:
        directory_path: Path to the directory to clean up.
        sandbox_root: Optional sandbox boundary. If provided, directory_path must be confined.

    Returns:
        True if the directory was successfully removed (or already absent), False on error.
    """
    raw_path = Path(directory_path)

    # If the directory target itself is a symlink, delete the symlink without following
    if raw_path.is_symlink():
        try:
            raw_path.unlink()
            logger.info("Removed symlink: %s", raw_path)
            return True
        except OSError as exc:
            logger.warning(
                "Failed to remove symlink %s: %s; deferred to background sweeper",
                raw_path,
                exc,
            )
            return False

    # Open the target itself with no-follow semantics, then work only through
    # descriptors. The confinement re-check happens on the descriptor held.
    try:
        confined = open_confined_directory(
            raw_path, sandbox_root if sandbox_root is not None else raw_path.parent
        )
    except FileNotFoundError:
        logger.debug("Directory does not exist for cleanup: %s", raw_path)
        return True
    except NotADirectoryError:
        try:
            raw_path.unlink()
            logger.info("Deleted file: %s", raw_path)
            return True
        except OSError as exc:
            logger.warning(
                "Failed to delete file %s: %s; deferred to background sweeper",
                raw_path,
                exc,
            )
            return False
    except PathTraversalException as exc:
        logger.error("Refusing to clean up %s: %s", raw_path, exc)
        return False

    parent_fd = -1
    tree_ok = False
    try:
        tree_ok = _remove_tree_relative(confined.fd)
        # Remove the directory itself through its parent, still no-follow.
        parent_fd = os.open(
            os.path.dirname(confined.path) or ".",
            os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC,
        )
        os.rmdir(os.path.basename(confined.path), dir_fd=parent_fd)
        logger.info("Removed sandbox directory: %s", confined.path)
        return tree_ok
    except OSError as exc:
        logger.warning(
            "Failed to remove temporary directory %s: %s; deferred to background sweeper",
            confined.path,
            exc,
        )
        return False
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)
        confined.close()
