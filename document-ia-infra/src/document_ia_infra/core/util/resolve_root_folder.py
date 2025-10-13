from importlib.resources import files, as_file
from pathlib import Path


def resolve_project_root(project_name: str) -> Path:
    """Resolve project root using importlib.resources to locate the package directory.
    Falls back to cwd if resolution fails.
    """
    try:
        pkg_trav = files(project_name)
        # Convert Traversable to a real filesystem Path
        with as_file(pkg_trav) as pkg_path:
            # pkg_path = .../document-ia-worker/src/document_ia_worker
            return Path(pkg_path).parent.parent  # → .../document-ia-worker
    except Exception:
        return Path.cwd()
