"""Password hashing utilities using bcrypt."""

import bcrypt

MAX_PASSWORD_BYTES = 72  # bcrypt ignores (or, in bcrypt>=5, rejects) anything beyond 72 bytes


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt.

    Raises:
        ValueError: If the UTF-8 encoded password exceeds 72 bytes.
    """
    encoded = password.encode()
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must not exceed {MAX_PASSWORD_BYTES} bytes when UTF-8 encoded")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.

    Passwords longer than 72 bytes can never match a hash created by `hash_password`, so they return False.
    """
    encoded = plain.encode()
    if len(encoded) > MAX_PASSWORD_BYTES:
        return False
    return bcrypt.checkpw(encoded, hashed.encode())
