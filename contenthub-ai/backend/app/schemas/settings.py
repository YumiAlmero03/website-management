from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SettingItemResponse(BaseModel):
    key: str
    category: str
    label: str
    description: str
    value_type: str
    value: Any
    is_secret: bool = False
    has_value: bool = False
    default_value: Any = None
    updated_at: datetime | None = None


class SettingsListResponse(BaseModel):
    categories: list[str]
    items: list[SettingItemResponse]


class SettingUpdateItem(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: Any


class SettingsBulkUpdateRequest(BaseModel):
    items: list[SettingUpdateItem] = Field(min_length=1, max_length=50)
