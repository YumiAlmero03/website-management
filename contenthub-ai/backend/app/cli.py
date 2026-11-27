from __future__ import annotations

import argparse
import contextlib
import getpass
import os
import sys
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.rate_limit import SlidingWindowRateLimiter
from app.database import check_database_connection, get_session_factory
from app.repositories.activity_log_repo import SQLAlchemyActivityLogRepository
from app.repositories.content_repo import SQLAlchemyContentRepository
from app.repositories.media_repo import SQLAlchemyMediaRepository
from app.repositories.scan_log_repo import SQLAlchemyScanLogRepository
from app.repositories.session_repo import SQLAlchemySessionRepository
from app.repositories.settings_repo import SQLAlchemySettingsRepository
from app.repositories.user_repo import SQLAlchemyUserRepository
from app.repositories.website_repo import SQLAlchemyWebsiteRepository
from app.repositories.website_source_repo import SQLAlchemyWebsiteSourceConfigRepository
from app.services.auth_service import AuthService
from app.services.monitoring.health_service import HealthService
from app.services.scan_executor import ScanExecutorService
from app.services.scanner.security import SafeHttpFetcher
from app.services.settings_service import SettingsService


def _build_scan_executor(db: Session, settings: Settings) -> ScanExecutorService:
    activity_repo = SQLAlchemyActivityLogRepository(db)
    settings_repo = SQLAlchemySettingsRepository(db)
    return ScanExecutorService(
        settings=settings,
        website_repo=SQLAlchemyWebsiteRepository(db),
        source_config_repo=SQLAlchemyWebsiteSourceConfigRepository(db),
        content_repo=SQLAlchemyContentRepository(db),
        scan_log_repo=SQLAlchemyScanLogRepository(db),
        media_repo=SQLAlchemyMediaRepository(db),
        activity_repo=activity_repo,
        health_service=HealthService(settings=settings),
        settings_service=SettingsService(
            settings=settings,
            settings_repo=settings_repo,
            activity_repo=activity_repo,
        ),
        fetcher=SafeHttpFetcher(settings=settings),
    )


def run_check_db(settings: Settings | None = None) -> int:
    cfg = settings or get_settings()
    diag = check_database_connection(settings=cfg)

    print(f"Database target : {diag.user}@{diag.host}:{diag.port}/{diag.database_name}")
    print(
        f"Connection pool : size={diag.pool_size}, "
        f"max_overflow={diag.max_overflow}, recycle={diag.pool_recycle}s"
    )
    if diag.uses_root_user:
        print(
            "WARNING         : DB_USER is 'root'. "
            "Use a dedicated least-privilege MySQL user in runtime."
        )

    if not diag.connected:
        print(f"Status          : UNAVAILABLE ({diag.error})")
        return 1

    print("Status          : CONNECTED")
    print(f"Server version  : {diag.server_version}")
    print(f"Character set   : {diag.character_set}")
    print(f"InnoDB enabled  : {diag.innodb_available}")
    print(f"Latency         : {diag.latency_ms} ms")

    if diag.character_set and diag.character_set.lower() != "utf8mb4":
        print("WARNING         : Database character set is not utf8mb4.")
    if diag.innodb_available is False:
        print("WARNING         : InnoDB storage engine is not reported as available.")
    return 0


def run_init_admin(
    *,
    email: str | None,
    display_name: str | None,
    password_env: str | None,
    auth_service: AuthService | None = None,
    input_fn: Callable[[str], str] = input,
    secret_input_fn: Callable[[str], str] = getpass.getpass,
) -> int:
    """Create the single administrator account interactively without any default password."""
    resolved_email = (email or input_fn("Administrator email: ")).strip()
    resolved_name = (display_name or input_fn("Administrator display name: ")).strip()

    if password_env:
        password = os.environ.get(password_env, "")
        if not password:
            print(
                f"Error: Environment variable '{password_env}' is empty or not set.",
                file=sys.stderr,
            )
            return 1
    else:
        password = secret_input_fn(
            "Administrator password (min 12 chars, upper/lower/digit/symbol): "
        )
        confirm = secret_input_fn("Confirm administrator password: ")
        if password != confirm:
            print("Error: Passwords do not match.", file=sys.stderr)
            return 1

    if auth_service is not None:
        try:
            user = auth_service.initialize_admin(
                email=resolved_email,
                display_name=resolved_name,
                password=password,
            )
        except AppError as exc:
            print(f"Error: {exc.detail}", file=sys.stderr)
            return 1
        print(f"Administrator created: {user.email} (id={user.id})")
        return 0

    settings = get_settings()
    db = get_session_factory()()
    try:
        service = AuthService(
            settings=settings,
            user_repo=SQLAlchemyUserRepository(db),
            session_repo=SQLAlchemySessionRepository(db),
            activity_repo=SQLAlchemyActivityLogRepository(db),
            rate_limiter=SlidingWindowRateLimiter(),
        )
        user = service.initialize_admin(
            email=resolved_email,
            display_name=resolved_name,
            password=password,
        )
        print(f"Administrator created: {user.email} (id={user.id})")
        return 0
    except AppError as exc:
        print(f"Error: {exc.detail}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        print(
            f"Database error ({type(exc).__name__}): "
            "verify MySQL connectivity and run `alembic upgrade head` first.",
            file=sys.stderr,
        )
        return 1
    finally:
        db.close()


def run_single_scan(
    *,
    scan_id: int,
    executor: ScanExecutorService | None = None,
) -> int:
    if executor is not None:
        result = executor.execute_scan(scan_id)
        print(
            f"Scan #{result.id}: status={result.status}, new={result.new_articles}, "
            f"updated={result.updated_articles}, failed={result.failed_articles}"
        )
        return 0 if result.status in {"completed", "partially_completed", "incomplete"} else 1

    settings = get_settings()
    db = get_session_factory()()
    try:
        service = _build_scan_executor(db, settings)
        result = service.execute_scan(scan_id)
        print(
            f"Scan #{result.id}: status={result.status}, new={result.new_articles}, "
            f"updated={result.updated_articles}, unchanged={result.unchanged_articles}, "
            f"failed={result.failed_articles}"
        )
        return 0 if result.status in {"completed", "partially_completed", "incomplete"} else 1
    except (AppError, SQLAlchemyError) as exc:
        print(f"Scan execution error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def run_due_scans(*, executor: ScanExecutorService | None = None) -> int:
    """Cron entrypoint: acquires a MySQL advisory lock and runs due website scans sequentially."""
    if executor is not None:
        summary = executor.run_due_scheduled_scans()
        print(
            f"Due scans summary: guardian={summary.guardian_status}, "
            f"paused={summary.paused_by_resource_guardian}, due={summary.due_websites_found}, "
            f"executed={summary.scans_executed}, succeeded={summary.scans_succeeded}, "
            f"failed={summary.scans_failed}"
        )
        return 0

    settings = get_settings()
    db = get_session_factory()()
    lock_name = "contenthub_due_scans_lock"
    lock_acquired = False
    try:
        got = db.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name}).scalar()
        if got != 1:
            print("Another scheduled scan process already holds the MySQL advisory lock; exiting.")
            return 0
        lock_acquired = True

        service = _build_scan_executor(db, settings)
        summary = service.run_due_scheduled_scans()
        print(
            f"Due scans summary: guardian={summary.guardian_status}, "
            f"paused={summary.paused_by_resource_guardian}, "
            f"stale_recovered={summary.stale_recovered}, "
            f"due={summary.due_websites_found}, executed={summary.scans_executed}, "
            f"succeeded={summary.scans_succeeded}, failed={summary.scans_failed}, "
            f"skipped_locked={summary.skipped_locked}"
        )
        return 0
    except SQLAlchemyError as exc:
        print(f"Scheduled scan DB error ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    finally:
        if lock_acquired:
            with contextlib.suppress(SQLAlchemyError):
                db.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="ContentHub AI administration & scanner CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "check-db",
        help="Verify MySQL connectivity, version, InnoDB, and utf8mb4.",
    )

    init_parser = subparsers.add_parser(
        "init-admin",
        help="Initialize the single administrator account (no default credentials).",
    )
    init_parser.add_argument("--email", help="Administrator email address.")
    init_parser.add_argument("--name", dest="display_name", help="Administrator display name.")
    init_parser.add_argument(
        "--password-env",
        help="Optional environment variable name holding the password.",
    )

    run_scan_parser = subparsers.add_parser(
        "run-scan",
        help="Claim and execute a single pending website scan by ID.",
    )
    run_scan_parser.add_argument("--scan-id", type=int, required=True, help="WebsiteScanLog ID.")

    subparsers.add_parser(
        "run-due-scans",
        help="Run due scheduled website scans sequentially under a MySQL advisory lock.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check-db":
        return run_check_db()
    if args.command == "init-admin":
        return run_init_admin(
            email=args.email,
            display_name=args.display_name,
            password_env=args.password_env,
        )
    if args.command == "run-scan":
        return run_single_scan(scan_id=args.scan_id)
    if args.command == "run-due-scans":
        return run_due_scans()

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
