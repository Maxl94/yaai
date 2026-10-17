"""Helpers for serving the built frontend (SPA) safely."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


def is_api_path(requested: str, api_prefix: str) -> bool:
    """Check whether a requested path (without leading slash) lies under the API prefix.

    Args:
        requested: Path from the URL (relative, without leading slash).
        api_prefix: API mount prefix such as ``/api/v1``; its first segment (``api``) is reserved for the API.

    Returns:
        True for ``api`` itself and anything below it, so unknown API routes never fall back to the SPA.
    """
    reserved = api_prefix.strip("/").split("/")[0]
    return requested == reserved or requested.startswith(f"{reserved}/")


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


def mount_spa(app: FastAPI, static_dir: Path, api_prefix: str) -> None:
    """Serve the built frontend, falling back to ``index.html`` for client-side routes.

    Unknown paths under the API prefix get a JSON 404 instead of the SPA, so API clients never receive HTML.

    Args:
        app: Application to register the routes on (register this after all API routers).
        static_dir: Root directory of the built frontend.
        api_prefix: API mount prefix such as ``/api/v1``.
    """
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if is_api_path(full_path, api_prefix):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        file_path = resolve_static_file(static_dir, full_path)
        return FileResponse(file_path or static_dir / "index.html")
