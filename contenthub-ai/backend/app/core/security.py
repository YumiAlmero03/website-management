from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.exceptions import ConfigurationError, ValidationAppError

_PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

# Allows standard domains and private internal admin domains such as admin@contenthub.local.
_EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def hash_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return bool(_PASSWORD_HASHER.verify(password_hash, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return bool(_PASSWORD_HASHER.check_needs_rehash(password_hash))
    except InvalidHashError:
        return True


def validate_password_strength(password: str) -> list[str]:
    """Validate administrator password requirements without permitting weak defaults."""
    errors: list[str] = []
    if len(password) < 12:
        errors.append("Password must be at least 12 characters long.")
    if not any(ch.islower() for ch in password):
        errors.append("Password must include at least one lowercase letter.")
    if not any(ch.isupper() for ch in password):
        errors.append("Password must include at least one uppercase letter.")
    if not any(ch.isdigit() for ch in password):
        errors.append("Password must include at least one number.")
    if not any(not ch.isalnum() for ch in password):
        errors.append("Password must include at least one symbol.")
    return errors


def validate_email_address(email: str) -> str:
    normalized = email.strip().lower()
    if not normalized or len(normalized) > 255 or not _EMAIL_REGEX.match(normalized):
        raise ValidationAppError("Please provide a valid administrator email address.")
    return normalized


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    return secrets.token_hex(32)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def constant_time_equals(expected: str, provided: str) -> bool:
    return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))


def _build_fernet(encryption_key: str) -> Fernet:
    key = encryption_key.strip()
    if not key or key.startswith("CHANGE_ME"):
        raise ConfigurationError(
            "APP_ENCRYPTION_KEY is not configured. Generate a valid Fernet key in .env."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise ConfigurationError("APP_ENCRYPTION_KEY is not a valid Fernet key.") from exc


def encrypt_secret(plaintext: str, encryption_key: str) -> str:
    fernet = _build_fernet(encryption_key)
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str, encryption_key: str) -> str:
    fernet = _build_fernet(encryption_key)
    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ConfigurationError(
            "Stored secret could not be decrypted with the active APP_ENCRYPTION_KEY."
        ) from exc


def mask_secret_hint(plaintext: str | None) -> str | None:
    """Return a display-safe masked preview without exposing credential characters."""
    if not plaintext:
        return None
    stripped = plaintext.strip()
    if not stripped:
        return None
    suffix = stripped[-4:] if len(stripped) > 6 else ""
    return f"••••••••{suffix}" if suffix else "••••••••"
