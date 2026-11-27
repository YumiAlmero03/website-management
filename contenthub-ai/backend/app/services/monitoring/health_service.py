from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import psutil

from app.config import Settings
from app.database import DatabaseDiagnostic, check_database_connection
from app.models.base import utc_now
from app.schemas.health import (
    DatabaseHealthInfo,
    HealthLiveResponse,
    ResourceThresholdsInfo,
    StoragePathStatus,
    SystemHealthResponse,
    SystemResourcesInfo,
)

STORAGE_SUBDIRS: tuple[str, ...] = ("images", "cache", "exports", "backups", "logs")


class HealthService:
    def __init__(
        self,
        *,
        settings: Settings,
        db_checker: Callable[[], DatabaseDiagnostic] | None = None,
    ) -> None:
        self.settings = settings
        self._db_checker = db_checker or (lambda: check_database_connection(settings=settings))

    def get_liveness(self) -> HealthLiveResponse:
        return HealthLiveResponse(
            status="ok",
            app_name=self.settings.app_name,
            version=self.settings.app_version,
            environment=self.settings.app_env,
            timezone=self.settings.app_timezone,
            timestamp=utc_now(),
        )

    def get_database_health(self) -> DatabaseHealthInfo:
        diag = self._db_checker()
        return DatabaseHealthInfo(
            connected=diag.connected,
            status=diag.status,
            database_name=diag.database_name,
            host=diag.host,
            port=diag.port,
            user=diag.user,
            uses_root_user=diag.uses_root_user,
            server_version=diag.server_version,
            character_set=diag.character_set,
            innodb_available=diag.innodb_available,
            latency_ms=diag.latency_ms,
            pool_size=diag.pool_size,
            max_overflow=diag.max_overflow,
            pool_recycle=diag.pool_recycle,
            error=diag.error,
        )

    def get_system_resources(
        self,
        *,
        effective_settings: dict[str, Any] | None = None,
    ) -> SystemResourcesInfo:
        overrides = effective_settings or {}
        thresholds = ResourceThresholdsInfo(
            cpu_warning_percent=float(
                overrides.get(
                    "resources.cpu_warning_percent", self.settings.resource_cpu_warning_percent
                )
            ),
            cpu_critical_percent=float(
                overrides.get(
                    "resources.cpu_critical_percent", self.settings.resource_cpu_critical_percent
                )
            ),
            ram_warning_percent=float(
                overrides.get(
                    "resources.ram_warning_percent", self.settings.resource_ram_warning_percent
                )
            ),
            load_avg_threshold=float(
                overrides.get(
                    "resources.load_avg_threshold", self.settings.resource_load_avg_threshold
                )
            ),
            max_concurrent_generation=int(
                overrides.get(
                    "resources.max_concurrent_generation",
                    self.settings.resource_max_concurrent_generation,
                )
            ),
            max_concurrent_browsers=int(
                overrides.get(
                    "resources.max_concurrent_browsers",
                    self.settings.resource_max_concurrent_browsers,
                )
            ),
            recheck_interval_minutes=int(
                overrides.get(
                    "resources.recheck_interval_minutes",
                    self.settings.resource_recheck_interval_minutes,
                )
            ),
        )

        cpu_percent = round(float(psutil.cpu_percent(interval=None)), 1)
        cpu_cores = psutil.cpu_count(logical=True) or 1
        mem = psutil.virtual_memory()
        ram_percent = round(float(mem.percent), 1)
        ram_used_mb = round(mem.used / (1024 * 1024), 1)
        ram_total_mb = round(mem.total / (1024 * 1024), 1)

        load_1m: float | None = None
        load_5m: float | None = None
        load_15m: float | None = None
        if hasattr(os, "getloadavg"):
            try:
                l1, l5, l15 = os.getloadavg()
                load_1m, load_5m, load_15m = round(l1, 2), round(l5, 2), round(l15, 2)
            except OSError:
                pass

        storage_root = self.settings.resolved_storage_root
        disk_target = storage_root if storage_root.exists() else storage_root.parent
        disk = psutil.disk_usage(str(disk_target))
        disk_percent = round(float(disk.percent), 1)
        disk_free_gb = round(disk.free / (1024 * 1024 * 1024), 2)

        reasons: list[str] = []
        guardian_status = "normal"

        if cpu_percent >= thresholds.cpu_critical_percent:
            guardian_status = "critical"
            reasons.append(
                f"CPU usage ({cpu_percent}%) reached critical threshold "
                f"({thresholds.cpu_critical_percent}%)."
            )
        elif cpu_percent >= thresholds.cpu_warning_percent:
            guardian_status = "warning"
            reasons.append(
                f"CPU usage ({cpu_percent}%) exceeded warning threshold "
                f"({thresholds.cpu_warning_percent}%)."
            )

        if ram_percent >= thresholds.ram_warning_percent:
            if guardian_status == "normal":
                guardian_status = "warning"
            reasons.append(
                f"RAM usage ({ram_percent}%) exceeded warning threshold "
                f"({thresholds.ram_warning_percent}%)."
            )

        if load_1m is not None and load_1m >= thresholds.load_avg_threshold:
            guardian_status = "critical"
            reasons.append(
                f"1-minute load average ({load_1m}) exceeded threshold "
                f"({thresholds.load_avg_threshold})."
            )

        return SystemResourcesInfo(
            cpu_percent=cpu_percent,
            cpu_cores=cpu_cores,
            ram_percent=ram_percent,
            ram_used_mb=ram_used_mb,
            ram_total_mb=ram_total_mb,
            load_avg_1m=load_1m,
            load_avg_5m=load_5m,
            load_avg_15m=load_15m,
            disk_percent=disk_percent,
            disk_free_gb=disk_free_gb,
            guardian_status=guardian_status,
            guardian_reasons=reasons,
            thresholds=thresholds,
        )

    def get_storage_statuses(self) -> list[StoragePathStatus]:
        root = self.settings.resolved_storage_root
        statuses: list[StoragePathStatus] = []
        for name in STORAGE_SUBDIRS:
            path = root / name
            exists = path.is_dir()
            writable = exists and os.access(path, os.W_OK)
            statuses.append(
                StoragePathStatus(
                    name=name,
                    path=str(path),
                    exists=exists,
                    writable=writable,
                )
            )
        return statuses

    def get_system_health(
        self,
        *,
        effective_settings: dict[str, Any] | None = None,
    ) -> SystemHealthResponse:
        db_health = self.get_database_health()
        resources = self.get_system_resources(effective_settings=effective_settings)
        storage_paths = self.get_storage_statuses()
        storage_ok = all(item.exists and item.writable for item in storage_paths)

        overall_status = "ok"
        if not db_health.connected or resources.guardian_status == "critical":
            overall_status = "degraded"
        elif resources.guardian_status == "warning" or not storage_ok or db_health.uses_root_user:
            overall_status = "warning"

        effective_tz = str(
            (effective_settings or {}).get("app.timezone", self.settings.app_timezone)
        )
        return SystemHealthResponse(
            status=overall_status,
            app_name=self.settings.app_name,
            version=self.settings.app_version,
            environment=self.settings.app_env,
            timezone=effective_tz,
            timestamp=utc_now(),
            database=db_health,
            resources=resources,
            storage_root=str(self.settings.resolved_storage_root),
            storage_paths=storage_paths,
        )
