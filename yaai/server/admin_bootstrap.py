"""Initial admin password handling for the bootstrap admin account.

The password is never written to the application log. It is either provided via
BOOTSTRAP_ADMIN_PASSWORD or generated and stored in a 0600 file (BOOTSTRAP_ADMIN_PASSWORD_FILE).
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


def deliver_generated_password(password: str) -> None:
    """Write a generated admin password to a 0600 file, falling back to a one-time stderr notice.

    The password itself is never passed to the logger; only the file path is logged.
    """
    path = Path(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE") or DEFAULT_PASSWORD_FILE)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(f"username: admin\npassword: {password}\n")
        os.chmod(path, 0o600)  # enforce permissions if the file already existed
    except OSError as exc:
        logger.warning("Could not write initial admin password file %s: %s", path, exc)
        print(
            "WARNING: could not store the initial admin password in a file. It is shown ONCE below; "
            f"change it immediately after first login.\n  username: admin\n  password: {password}",
            file=sys.stderr,
        )
        return
    logger.info(
        "Created default admin account (username: admin). Initial password written to %s "
        "(readable by owner only). Change it after first login and delete the file.",
        path.resolve(),
    )
