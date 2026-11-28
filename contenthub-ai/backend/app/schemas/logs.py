from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import PaginationMeta


class ActivityLogItem(BaseModel):
    id: int
    user_id: int | None = None
    actor_type: str
    category: str
    action: str
    level: str
    message: str
    metadata: dict[str, Any] | None = None
    ip_address: str | None = None
    created_at: datetime


class ActivityLogListResponse(BaseModel):
    items: list[ActivityLogItem]
    meta: PaginationMeta


class BackgroundFunctionItem(BaseModel):
    function: str
    status: str
    count: int = 0
    details: str


class BackgroundFunctionsResponse(BaseModel):
    items: list[BackgroundFunctionItem]
