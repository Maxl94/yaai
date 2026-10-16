"""Initial admin password handling for the bootstrap admin account.

The password is never written to the application log. It is either provided via
BOOTSTRAP_ADMIN_PASSWORD or generated and stored in a new 0600 file (BOOTSTRAP_ADMIN_PASSWORD_FILE). Only if that file cannot
be created is the generated password printed once to stderr.
"""

import logging
import os
import secrets
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 12
DEFAULT_PASSWORD_FILE = "admin-initial-password.txt"  # noqa: S105


def resolve_admin_password() -> tuple[str, bool]:
    """Return the initial admin password and whether it was generated.

    Returns:
        Tuple of (password, generated). ``generated`` is False when BOOTSTRAP_ADMIN_PASSWORD is used.

    Raises:
        RuntimeError: If BOOTSTRAP_ADMIN_PASSWORD is set but shorter than 12 characters.
    """
    configured = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    if not configured:
        return secrets.token_urlsafe(16), True
    if len(configured) < MIN_PASSWORD_LENGTH:
        raise RuntimeError(
            f"BOOTSTRAP_ADMIN_PASSWORD is too short ({len(configured)} characters): "
            f"expected at least {MIN_PASSWORD_LENGTH}."
        )
    return configured, False


def deliver_generated_password(password: str) -> Path | None:
    """Store a generated admin password in a new 0600 file, or print it once to stderr as a fallback.

    The file is created exclusively (never overwritten, symlinks are not followed). If it cannot be
    created, for example because the directory is not writable or the file already exists, the password
    is printed ONCE to stderr (not through logging). Note that in containers stderr usually ends up in
    the log stream, so set BOOTSTRAP_ADMIN_PASSWORD or a writable BOOTSTRAP_ADMIN_PASSWORD_FILE instead.

    Returns:
        The path of the created password file, or None if the stderr fallback was used.

    Raises:
        RuntimeError: If the password could be delivered neither via file nor via stderr.
    """
    path = Path(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE") or DEFAULT_PASSWORD_FILE)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(f"username: admin\npassword: {password}\n")
    except OSError as exc:
        logger.warning(
            "Could not create initial admin password file %s (%s); existing files are never overwritten. "
            "Printing the password once to stderr.",
            path,
            exc,
        )
        _print_password_to_stderr(password)
        return None
    logger.info(
        "Created default admin account (username: admin). Initial password written to %s "
        "(readable by owner only). Change it after first login and delete the file.",
        path.resolve(),
    )
    return path


def _print_password_to_stderr(password: str) -> None:
    try:
        print(
            "WARNING: could not store the initial admin password in a file. It is shown ONCE below; "
            f"change it immediately after first login.\n  username: admin\n  password: {password}",
            file=sys.stderr,
            flush=True,
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError("set BOOTSTRAP_ADMIN_PASSWORD or a writable BOOTSTRAP_ADMIN_PASSWORD_FILE") from exc
