import pytest

from app.core.security import (
    generate_secure_token,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
)


def test_password_hashing_and_verification():
    raw = "WaveNxD_Secure_Pass_2026!"
    hashed = hash_password(raw)

    assert hashed != raw
    assert hashed.startswith("$argon2id$")
    assert verify_password(raw, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False


def test_password_verification_with_malformed_hashes():
    raw = "ValidPassword123!"

    # Completely bogus hash
    assert verify_password(raw, "not-a-valid-argon2-hash") is False

    # Empty or None hash
    assert verify_password(raw, "") is False
    assert verify_password(raw, None) is False
    assert verify_password("", "$argon2id$v=19$m=65536,t=3,p=4$fake$fake") is False

    # Truncated hash
    assert verify_password(raw, "$argon2id$v=19$m=65536,t=3,p=4$") is False


def test_password_strength_validation():
    # Valid passwords
    valid, msg = validate_password_strength("MyStrongP@ssw0rd!")
    assert valid is True
    assert msg is None

    # Too short
    valid, msg = validate_password_strength("Short1!")
    assert valid is False
    assert "at least 8 characters" in msg

    # Whitespace at edges
    valid, msg = validate_password_strength("  Password123! ")
    assert valid is False
    assert "whitespace" in msg

    # Too repetitive
    valid, msg = validate_password_strength("aaaaaaaa")
    assert valid is False
    assert "varied" in msg

    # Too long
    valid, msg = validate_password_strength("a" * 129)
    assert valid is False
    assert "exceed" in msg


def test_token_hashing_and_generation():
    token1 = generate_secure_token()
    token2 = generate_secure_token()

    assert len(token1) >= 32
    assert token1 != token2

    hash1 = hash_token(token1)
    hash2 = hash_token(token1)
    hash3 = hash_token(token2)

    # Deterministic SHA-256 hash
    assert len(hash1) == 64
    assert hash1 == hash2
    assert hash1 != hash3
