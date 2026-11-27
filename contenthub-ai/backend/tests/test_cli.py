from __future__ import annotations

from typing import Any

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
