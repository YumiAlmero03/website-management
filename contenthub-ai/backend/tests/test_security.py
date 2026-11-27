from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.core.exceptions import ConfigurationError, ValidationAppError
from app.core.logging import REDACTED, redact_mapping, redact_text
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.security import (
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_token,
    validate_email_address,
    validate_password_strength,
    verify_password,
)


def test_argon2id_hashing_and_verification() -> None:
    raw = "AdminSecret#2026!"
    hashed = hash_password(raw)
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, raw) is True
    assert verify_password(hashed, "WrongSecret#2026!") is False


def test_password_strength_rules() -> None:
    assert validate_password_strength("short") != []
    assert validate_password_strength("alllowercase1234!") != []
    assert validate_password_strength("NoDigitsOrSymbolHere") != []
    assert validate_password_strength("ValidPass#2026!") == []


def test_email_validation_supports_private_local_domains() -> None:
    assert validate_email_address("  Admin@ContentHub.LOCAL ") == "admin@contenthub.local"
    assert validate_email_address("ops@example.com") == "ops@example.com"
    with pytest.raises(ValidationAppError):
        validate_email_address("not-an-email")


def test_fernet_encryption_roundtrip_and_invalid_key_failure() -> None:
    key = Fernet.generate_key().decode("utf-8")
    ciphertext = encrypt_secret("super-sensitive-api-key", key)
    assert "super-sensitive-api-key" not in ciphertext
    assert decrypt_secret(ciphertext, key) == "super-sensitive-api-key"

    with pytest.raises(ConfigurationError):
        encrypt_secret("secret", "CHANGE_ME_GENERATE_VALID_FERNET_KEY")

    with pytest.raises(ConfigurationError):
        decrypt_secret(ciphertext, Fernet.generate_key().decode("utf-8"))


def test_log_and_metadata_redaction() -> None:
    redacted_map = redact_mapping(
        {
            "email": "admin@contenthub.local",
            "password": "plain-password",
            "nested": {
                "api_key": "AIzaSySecretKey",
                "authorization": "Bearer abc.def.ghi",
                "safe_note": "token=my_leaked_token",
            },
        }
    )
    assert redacted_map is not None
    assert redacted_map["email"] == "admin@contenthub.local"
    assert redacted_map["password"] == REDACTED
    assert redacted_map["nested"]["api_key"] == REDACTED
    assert redacted_map["nested"]["authorization"] == REDACTED
    assert "my_leaked_token" not in redacted_map["nested"]["safe_note"]
    assert REDACTED in redact_text("Authorization: Bearer secret_jwt_token_123")


def test_sliding_window_rate_limiter_enforces_and_expires() -> None:
    clock_now = [100.0]
    limiter = SlidingWindowRateLimiter(
        max_attempts=2,
        window_seconds=60,
        clock=lambda: clock_now[0],
    )

    assert limiter.check("127.0.0.1:admin")[0] is True
    limiter.record_failure("127.0.0.1:admin")
    assert limiter.check("127.0.0.1:admin")[0] is True
    limiter.record_failure("127.0.0.1:admin")

    allowed, retry_after = limiter.check("127.0.0.1:admin")
    assert allowed is False
    assert retry_after == 60

    clock_now[0] = 161.0
    assert limiter.check("127.0.0.1:admin")[0] is True

    limiter.record_failure("127.0.0.1:admin")
    limiter.reset("127.0.0.1:admin")
    assert hash_token("abc") == hash_token("abc")
    assert limiter.check("127.0.0.1:admin")[0] is True
