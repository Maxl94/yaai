"""Helpers for serving the built frontend (SPA) safely."""

from pathlib import Path


def resolve_static_file(static_dir: Path, requested: str) -> Path | None:
    """Resolve a requested path to an existing file inside ``static_dir``.

    Args:
        static_dir: Root directory of the built frontend.
        requested: Path from the URL (relative, without leading slash).

    Returns:
        The resolved file path, or None if it does not exist or escapes ``static_dir``
        (path traversal, symlinks or sibling directories sharing the same name prefix).
    """
    root = static_dir.resolve()
    try:
        candidate = (root / requested).resolve()
    except ValueError:  # e.g. embedded null byte
        return None
    if not candidate.is_relative_to(root):
        return None
    return candidate if candidate.is_file() else None
