import hashlib
import logging
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

logger = logging.getLogger(__name__)

# Argon2id password hasher instance
_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hashes a plaintext password using Argon2id."""
    return _password_hasher.hash(password)


def verify_password(password: str, hashed_password: str | None) -> bool:
    """
    Safely verifies a plaintext password against an Argon2id hash.
    Catches verification mismatches and malformed hashes without
    leaking internal exception details.
    """
    if not hashed_password or not password:
        return False

    try:
        return _password_hasher.verify(hashed_password, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError, ValueError):
        return False
    except Exception as exc:
        logger.warning("Unexpected error during password verification: %s", type(exc).__name__)
        return False


def validate_password_strength(password: str) -> tuple[bool, str | None]:
    """
    Validates password strength for new credentials.
    Requires at least 8 characters, non-whitespace content,
    and a maximum length to prevent DoS attacks.
    """
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long"

    if len(password) > 128:
        return False, "Password cannot exceed 128 characters"

    if password.strip() != password:
        return False, "Password cannot begin or end with whitespace"

    if len(set(password)) < 4:
        return False, "Password must contain more varied characters"

    return True, None


def hash_token(token: str) -> str:
    """
    Computes a deterministic SHA-256 hash of a cryptographic token
    (e.g., session token or invitation token) for secure database storage and lookup.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_secure_token(nbytes: int = 32) -> str:
    """Generates a cryptographically strong, URL-safe random token."""
    return secrets.token_urlsafe(nbytes)
