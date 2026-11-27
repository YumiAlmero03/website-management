from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class HealthLiveResponse(BaseModel):
    status: str
    app_name: str
    version: str
    environment: str
    timezone: str
    timestamp: datetime


class DatabaseHealthInfo(BaseModel):
    connected: bool
    status: str
    database_name: str
    host: str
    port: int
    user: str
    uses_root_user: bool
    server_version: str | None = None
    character_set: str | None = None
    innodb_available: bool | None = None
    latency_ms: float | None = None
    pool_size: int
    max_overflow: int
    pool_recycle: int
    error: str | None = None


class ResourceThresholdsInfo(BaseModel):
    cpu_warning_percent: float
    cpu_critical_percent: float
    ram_warning_percent: float
    load_avg_threshold: float
    max_concurrent_generation: int
    max_concurrent_browsers: int
    recheck_interval_minutes: int


class SystemResourcesInfo(BaseModel):
    cpu_percent: float
    cpu_cores: int
    ram_percent: float
    ram_used_mb: float
    ram_total_mb: float
    load_avg_1m: float | None = None
    load_avg_5m: float | None = None
    load_avg_15m: float | None = None
    disk_percent: float
    disk_free_gb: float
    guardian_status: str
    guardian_reasons: list[str]
    thresholds: ResourceThresholdsInfo


class StoragePathStatus(BaseModel):
    name: str
    path: str
    exists: bool
    writable: bool


class SystemHealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    environment: str
    timezone: str
    timestamp: datetime
    database: DatabaseHealthInfo
    resources: SystemResourcesInfo
    storage_root: str
    storage_paths: list[StoragePathStatus]
