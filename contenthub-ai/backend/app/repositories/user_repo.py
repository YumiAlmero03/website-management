from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import utc_now_naive
from app.models.user import User


class UserRepositoryProtocol(Protocol):
    def count_all(self) -> int: ...

    def get_by_id(self, user_id: int) -> User | None: ...

    def get_by_email(self, email: str) -> User | None: ...

    def create(self, *, email: str, display_name: str, password_hash: str) -> User: ...

    def update_login_metadata(
        self,
        user_id: int,
        *,
        last_login_at: datetime,
        password_hash: str | None = None,
    ) -> User | None: ...


class SQLAlchemyUserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def count_all(self) -> int:
        count = self.db.execute(select(func.count()).select_from(User)).scalar_one()
        return int(count)

    def get_by_id(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.strip().lower())
        return self.db.execute(stmt).scalar_one_or_none()

    def create(self, *, email: str, display_name: str, password_hash: str) -> User:
        now = utc_now_naive()
        user = User(
            email=email.strip().lower(),
            display_name=display_name.strip(),
            password_hash=password_hash,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_login_metadata(
        self,
        user_id: int,
        *,
        last_login_at: datetime,
        password_hash: str | None = None,
    ) -> User | None:
        user = self.db.get(User, user_id)
        if user is None:
            return None
        user.last_login_at = last_login_at.replace(tzinfo=None)
        if password_hash is not None:
            user.password_hash = password_hash
        user.updated_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(user)
        return user
