from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class AuthSessionResponse(BaseModel):
    user: AdminUserResponse
    csrf_token: str
    expires_at: datetime


class AuthStatusResponse(BaseModel):
    admin_initialized: bool
    authenticated: bool
    app_name: str
    database_connected: bool
    registration_enabled: bool = False


class LogoutResponse(BaseModel):
    message: str
