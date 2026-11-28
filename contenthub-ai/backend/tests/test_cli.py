from __future__ import annotations

from typing import Any

import pytest

from app.cli import run_init_admin
from app.config import Settings
from app.services.auth_service import AuthService


def test_cli_init_admin_creates_single_admin_and_rejects_weak_or_duplicate(
    test_settings: Settings,
    memory_repos: dict[str, Any],
) -> None:
    service = AuthService(
        settings=test_settings,
        user_repo=memory_repos["users"],
        session_repo=memory_repos["sessions"],
        activity_repo=memory_repos["activities"],
        rate_limiter=memory_repos["rate_limiter"],
    )

    # Mismatched confirmation passwords rejected.
    prompts = iter(["StrongAdmin#2026!", "Different#2026!"])
    code = run_init_admin(
        email="admin@contenthub.local",
        display_name="Lead Admin",
        password_env=None,
        auth_service=service,
        secret_input_fn=lambda _prompt: next(prompts),
    )
    assert code == 1
    assert memory_repos["users"].count_all() == 0

    # Weak password rejected.
    weak_prompts = iter(["password", "password"])
    code = run_init_admin(
        email="admin@contenthub.local",
        display_name="Lead Admin",
        password_env=None,
        auth_service=service,
        secret_input_fn=lambda _prompt: next(weak_prompts),
    )
    assert code == 1
    assert memory_repos["users"].count_all() == 0

    # Strong credentials succeed.
    strong_prompts = iter(["StrongAdmin#2026!", "StrongAdmin#2026!"])
    code = run_init_admin(
        email="admin@contenthub.local",
        display_name="Lead Admin",
        password_env=None,
        auth_service=service,
        secret_input_fn=lambda _prompt: next(strong_prompts),
    )
    assert code == 0
    assert memory_repos["users"].count_all() == 1

    # Second administrator initialization is rejected (single-admin policy).
    second_prompts = iter(["AnotherStrong#2026!", "AnotherStrong#2026!"])
    code = run_init_admin(
        email="second@contenthub.local",
        display_name="Second Admin",
        password_env=None,
        auth_service=service,
        secret_input_fn=lambda _prompt: next(second_prompts),
    )
    assert code == 1
    assert memory_repos["users"].count_all() == 1


def test_cli_init_admin_password_env_and_check_db(
    monkeypatch: Any,
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
) -> None:
    from app import cli

    service = AuthService(
        settings=test_settings,
        user_repo=memory_repos["users"],
        session_repo=memory_repos["sessions"],
        activity_repo=memory_repos["activities"],
        rate_limiter=memory_repos["rate_limiter"],
    )
    monkeypatch.setenv("TEST_ADMIN_PW", "EnvStrongAdmin#2026!")
    code = cli.run_init_admin(
        email="ops@contenthub.local",
        display_name="Ops Admin",
        password_env="TEST_ADMIN_PW",
        auth_service=service,
    )
    assert code == 0
    assert memory_repos["users"].count_all() == 1

    monkeypatch.setattr(cli, "check_database_connection", lambda settings=None: db_diagnostic_ok)
    assert cli.run_check_db(settings=test_settings) == 0


def test_default_subprocess_dispatcher_uses_existing_backend_root(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    from app.config import BACKEND_ROOT
    from app.services import scan_executor

    captured: dict[str, Any] = {}

    def fake_popen(cmd: list[str], **kwargs: Any) -> object:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(scan_executor.subprocess, "Popen", fake_popen)

    scan_executor.default_subprocess_dispatcher(42)

    assert captured["cmd"][-4:] == ["app.cli", "run-scan", "--scan-id", "42"]
    assert captured["kwargs"]["cwd"] == str(BACKEND_ROOT)
    assert BACKEND_ROOT.is_dir()


def test_enqueue_scan_marks_failed_when_dispatcher_raises(
    test_settings: Settings,
    memory_repos: dict[str, Any],
    db_diagnostic_ok: Any,
) -> None:
    from app.services.monitoring.health_service import HealthService
    from app.services.scan_executor import ScanExecutorService
    from app.services.scanner.security import SafeHttpFetcher
    from app.services.settings_service import SettingsService

    cat = memory_repos["categories"].create({"name": "Casino", "slug": "casino"})
    site = memory_repos["websites"].create(
        {
            "category_id": cat.id,
            "name": "Fail Dispatch",
            "brand_name": "Fail Dispatch",
            "domain": "example.com",
            "website_type": "custom",
            "discovery_method": "auto",
            "scan_interval_minutes": 1440,
        }
    )

    def broken_dispatcher(_scan_id: int) -> None:
        raise RuntimeError("spawn failure")

    executor = ScanExecutorService(
        settings=test_settings,
        website_repo=memory_repos["websites"],
        source_config_repo=memory_repos["sources"],
        content_repo=memory_repos["contents"],
        scan_log_repo=memory_repos["scans"],
        media_repo=memory_repos["media"],
        activity_repo=memory_repos["activities"],
        health_service=HealthService(settings=test_settings, db_checker=lambda: db_diagnostic_ok),
        settings_service=SettingsService(
            settings=test_settings,
            settings_repo=memory_repos["settings"],
            activity_repo=memory_repos["activities"],
        ),
        fetcher=SafeHttpFetcher(settings=test_settings),
        dispatcher=broken_dispatcher,
    )

    with pytest.raises(RuntimeError, match="spawn failure"):
        executor.enqueue_scan(site.id, trigger_type="manual", dispatch=True)

    assert memory_repos["scans"].get_active_for_website(site.id) is None
    latest, _total = memory_repos["scans"].list_for_website(site.id, page=1, page_size=5)
    assert latest[0].status == "failed"
    assert "Failed to dispatch scan worker" in (latest[0].error_message or "")


def test_safe_http_fetcher_connection_pooling_and_close(test_settings: Settings) -> None:
    from app.services.scanner.security import SafeHttpFetcher

    fetcher = SafeHttpFetcher(settings=test_settings, resolver=lambda _h, _p: ["93.184.216.34"])
    client1 = fetcher._get_pooled_client("example.com", 10.0)
    client2 = fetcher._get_pooled_client("example.com", 10.0)
    assert client1 is client2
    assert len(fetcher._clients) == 1

    fetcher._drop_pooled_clients("example.com")
    assert len(fetcher._clients) == 0

    client3 = fetcher._get_pooled_client("example.com", 10.0)
    fetcher.close()
    assert len(fetcher._clients) == 0
    assert client3.is_closed


def test_cli_publishing_commands_and_parser(
    monkeypatch: Any,
    test_settings: Settings,
) -> None:
    from unittest.mock import MagicMock

    from app import cli

    parser = cli.build_parser()
    args_single = parser.parse_args(["run-publish-job", "--job-id", "77"])
    assert args_single.command == "run-publish-job"
    assert args_single.job_id == 77

    args_due = parser.parse_args(["run-due-publishes", "--limit", "5"])
    assert args_due.command == "run-due-publishes"
    assert args_due.limit == 5

    fake_service = MagicMock()
    fake_service.execute_job.return_value = MagicMock(status="published")
    fake_service.run_due_jobs.return_value = [
        MagicMock(status="published"),
        MagicMock(status="deferred"),
    ]

    assert cli.run_single_publish_job(job_id=77, service=fake_service) == 0
    assert cli.run_due_publishes(limit=5, service=fake_service) == 0

    fake_service.execute_job.return_value = MagicMock(status="failed")
    assert cli.run_single_publish_job(job_id=77, service=fake_service) == 1

    from sqlalchemy.exc import SQLAlchemyError

    monkeypatch.setattr(cli, "_build_publishing_service", MagicMock())
    monkeypatch.setattr(cli, "get_session_factory", MagicMock(side_effect=lambda: MagicMock()))
    bad_db = MagicMock()
    bad_db.execute.side_effect = SQLAlchemyError("db error")
    monkeypatch.setattr(cli, "get_session_factory", lambda: (lambda: bad_db))
    assert cli.run_due_publishes(limit=5) == 1


def test_cli_daily_indexing_command_and_parser() -> None:
    from unittest.mock import MagicMock

    from app import cli

    parser = cli.build_parser()
    args = parser.parse_args(["run-daily-indexing"])
    assert args.command == "run-daily-indexing"

    fake_indexing = MagicMock()
    fake_indexing.run_daily_indexing.return_value = {
        "state": "completed",
        "progress": 10,
        "total": 10,
        "processed": 10,
        "indexed": 10,
        "skipped": 0,
        "ready": 0,
        "failed": 0,
    }
    assert cli.run_daily_indexing(service=fake_indexing) == 0
    fake_indexing.run_daily_indexing.assert_called_once_with(execute_inline=True)

