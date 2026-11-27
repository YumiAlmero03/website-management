from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.config import Settings
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    RateLimitError,
    ValidationAppError,
)
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.security import (
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    validate_email_address,
    validate_password_strength,
    verify_password,
)
from app.models.base import ensure_utc, utc_now
from app.models.session import AdminSession
from app.models.user import User
from app.repositories.activity_log_repo import ActivityLogRepositoryProtocol
from app.repositories.session_repo import SessionRepositoryProtocol
from app.repositories.user_repo import UserRepositoryProtocol

# Precomputed Argon2id dummy hash so unknown-email login attempts perform comparable work.
_DUMMY_PASSWORD_HASH = hash_password("ContentHub!DummyTimingGuard#2026")


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    session: AdminSession
    raw_token: str | None = None


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        user_repo: UserRepositoryProtocol,
        session_repo: SessionRepositoryProtocol,
        activity_repo: ActivityLogRepositoryProtocol,
        rate_limiter: SlidingWindowRateLimiter,
    ) -> None:
        self.settings = settings
        self.user_repo = user_repo
        self.session_repo = session_repo
        self.activity_repo = activity_repo
        self.rate_limiter = rate_limiter

    def is_admin_initialized(self) -> bool:
        return self.user_repo.count_all() > 0

    def initialize_admin(self, *, email: str, display_name: str, password: str) -> User:
        """Create the single administrator account via CLI without default credentials."""
        if self.user_repo.count_all() > 0:
            raise ConflictError(
                "An administrator account already exists. "
                "Single-administrator mode allows only one account."
            )

        normalized_email = validate_email_address(email)
        clean_name = display_name.strip()
        if len(clean_name) < 2 or len(clean_name) > 120:
            raise ValidationAppError("Display name must be between 2 and 120 characters.")

        pw_errors = validate_password_strength(password)
        if pw_errors:
            raise ValidationAppError(" ".join(pw_errors))

        user = self.user_repo.create(
            email=normalized_email,
            display_name=clean_name,
            password_hash=hash_password(password),
        )
        self.activity_repo.create(
            user_id=user.id,
            actor_type="cli",
            category="auth",
            action="admin.initialized",
            level="info",
            message=f"Administrator account initialized for {user.email}.",
            metadata={"email": user.email},
        )
        return user

    def login(
        self,
        *,
        email: str,
        password: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> AuthenticatedSession:
        normalized_email = email.strip().lower()
        rate_key = f"{ip_address or 'unknown'}:{normalized_email}"

        allowed, retry_after = self.rate_limiter.check(rate_key)
        if not allowed:
            self.activity_repo.create(
                user_id=None,
                actor_type="anonymous",
                category="auth",
                action="auth.login_rate_limited",
                level="warning",
                message="Login blocked due to repeated failed attempts.",
                metadata={"email": normalized_email, "retry_after_seconds": retry_after},
                ip_address=ip_address,
            )
            raise RateLimitError(retry_after)

        user = self.user_repo.get_by_email(normalized_email)
        if user is None:
            verify_password(_DUMMY_PASSWORD_HASH, password)
            self.rate_limiter.record_failure(rate_key)
            self.activity_repo.create(
                user_id=None,
                actor_type="anonymous",
                category="auth",
                action="auth.login_failed",
                level="warning",
                message="Failed administrator login attempt.",
                metadata={"email": normalized_email, "reason": "invalid_credentials"},
                ip_address=ip_address,
            )
            raise AuthenticationError("Invalid email or password.", code="INVALID_CREDENTIALS")

        if not user.is_active:
            self.rate_limiter.record_failure(rate_key)
            self.activity_repo.create(
                user_id=user.id,
                actor_type="admin",
                category="auth",
                action="auth.login_blocked_inactive",
                level="warning",
                message="Login attempt rejected for inactive administrator account.",
                metadata={"email": user.email},
                ip_address=ip_address,
            )
            raise AuthenticationError("Administrator account is inactive.", code="ACCOUNT_INACTIVE")

        if not verify_password(user.password_hash, password):
            self.rate_limiter.record_failure(rate_key)
            self.activity_repo.create(
                user_id=user.id,
                actor_type="anonymous",
                category="auth",
                action="auth.login_failed",
                level="warning",
                message="Failed administrator login attempt.",
                metadata={"email": user.email, "reason": "invalid_credentials"},
                ip_address=ip_address,
            )
            raise AuthenticationError("Invalid email or password.", code="INVALID_CREDENTIALS")

        self.rate_limiter.reset(rate_key)

        now = utc_now()
        updated_hash = (
            hash_password(password) if password_needs_rehash(user.password_hash) else None
        )
        refreshed_user = self.user_repo.update_login_metadata(
            user.id,
            last_login_at=now,
            password_hash=updated_hash,
        )
        active_user = refreshed_user or user

        raw_token = generate_session_token()
        csrf_token = generate_csrf_token()
        expires_at = now + timedelta(minutes=self.settings.session_ttl_minutes)

        session = self.session_repo.create(
            user_id=active_user.id,
            token_hash=hash_token(raw_token),
            csrf_token=csrf_token,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.activity_repo.create(
            user_id=active_user.id,
            actor_type="admin",
            category="auth",
            action="auth.login_succeeded",
            level="info",
            message=f"Administrator {active_user.email} signed in.",
            metadata={"session_id": session.id},
            ip_address=ip_address,
        )
        return AuthenticatedSession(user=active_user, session=session, raw_token=raw_token)

    def resolve_session(self, raw_token: str | None) -> AuthenticatedSession | None:
        if not raw_token:
            return None

        session = self.session_repo.get_by_token_hash(hash_token(raw_token))
        if session is None or session.revoked_at is not None:
            return None

        now = utc_now()
        expires_at = ensure_utc(session.expires_at)
        if expires_at is None or expires_at <= now:
            return None

        user = self.user_repo.get_by_id(session.user_id)
        if user is None or not user.is_active:
            return None

        self.session_repo.touch(session.id, seen_at=now)
        return AuthenticatedSession(user=user, session=session)

    def logout(self, auth: AuthenticatedSession, *, ip_address: str | None) -> None:
        self.session_repo.revoke(auth.session.id, revoked_at=utc_now())
        self.activity_repo.create(
            user_id=auth.user.id,
            actor_type="admin",
            category="auth",
            action="auth.logout",
            level="info",
            message=f"Administrator {auth.user.email} signed out.",
            metadata={"session_id": auth.session.id},
            ip_address=ip_address,
        )
