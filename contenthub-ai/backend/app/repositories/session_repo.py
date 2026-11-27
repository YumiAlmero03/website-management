from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.session import AdminSession


class SessionRepositoryProtocol(Protocol):
    def create(
        self,
        *,
        user_id: int,
        token_hash: str,
        csrf_token: str,
        expires_at: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> AdminSession: ...

    def get_by_token_hash(self, token_hash: str) -> AdminSession | None: ...

    def touch(self, session_id: int, *, seen_at: datetime) -> None: ...

    def revoke(self, session_id: int, *, revoked_at: datetime) -> None: ...

    def count_active(self, *, now: datetime) -> int: ...


class SQLAlchemySessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        user_id: int,
        token_hash: str,
        csrf_token: str,
        expires_at: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> AdminSession:
        now = utc_now_naive()
        session = AdminSession(
            user_id=user_id,
            token_hash=token_hash,
            csrf_token=csrf_token,
            ip_address=ip_address[:64] if ip_address else None,
            user_agent=user_agent[:512] if user_agent else None,
            expires_at=expires_at.replace(tzinfo=None),
            last_seen_at=now,
            created_at=now,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_by_token_hash(self, token_hash: str) -> AdminSession | None:
        stmt = select(AdminSession).where(AdminSession.token_hash == token_hash)
        return self.db.execute(stmt).scalar_one_or_none()

    def touch(self, session_id: int, *, seen_at: datetime) -> None:
        session = self.db.get(AdminSession, session_id)
        if session is not None:
            session.last_seen_at = seen_at.replace(tzinfo=None)
            self.db.commit()

    def revoke(self, session_id: int, *, revoked_at: datetime) -> None:
        session = self.db.get(AdminSession, session_id)
        if session is not None and session.revoked_at is None:
            session.revoked_at = revoked_at.replace(tzinfo=None)
            self.db.commit()

    def count_active(self, *, now: datetime) -> int:
        naive_now = now.replace(tzinfo=None)
        stmt = (
            select(func.count())
            .select_from(AdminSession)
            .where(AdminSession.revoked_at.is_(None), AdminSession.expires_at > naive_now)
        )
        return int(self.db.execute(stmt).scalar_one())
