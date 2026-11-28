from __future__ import annotations

import base64
import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.dialects import mysql

from app.config import Settings
from app.core.exceptions import ValidationAppError
from app.models.indexing import IndexingJob
from app.services.indexing_service import IndexingService


def test_start_builds_mysql_compatible_query_and_dispatches_job(
    test_settings: Settings,
) -> None:
    site = SimpleNamespace(
        id=1,
        gsc_property_url="https://example.com/",
        encrypted_gsc_service_account_json="encrypted-test-key",
    )
    content = SimpleNamespace(
        id=23,
        canonical_url="https://example.com/article",
        url="https://example.com/article",
        google_index_status="uninspected",
    )
    active_job_result = SimpleNamespace(scalar_one_or_none=lambda: None)
    eligible_content_result = SimpleNamespace(scalars=lambda: [content])
    latest_job = SimpleNamespace(
        status="queued",
        progress_count=0,
        requested_count=1,
        processed_count=0,
        indexed_count=0,
        skipped_count=0,
        ready_count=0,
        failed_count=0,
    )
    latest_job_result = SimpleNamespace(scalar_one_or_none=lambda: latest_job)
    db = Mock(spec=["get", "execute", "add", "flush", "commit", "refresh"])
    db.get.return_value = site
    db.execute.side_effect = [
        active_job_result,
        eligible_content_result,
        active_job_result,
        latest_job_result,
    ]
    db.add.side_effect = lambda job: setattr(job, "id", 72)
    dispatched: list[int] = []
    service = IndexingService(
        db=db,
        settings=test_settings,
        health_service=Mock(),
        dispatcher=dispatched.append,
    )

    status = service.start(1)

    eligible_query = db.execute.call_args_list[1].args[0]
    compiled_query = str(eligible_query.compile(dialect=mysql.dialect()))
    assert "NULLS LAST" not in compiled_query
    assert "NULLS FIRST" not in compiled_query
    assert status["state"] == "queued"
    assert status["total"] == 1
    assert dispatched == [72]
    assert content.google_index_status == "queued"


def test_start_restores_content_if_worker_cannot_be_launched(
    test_settings: Settings,
) -> None:
    content = SimpleNamespace(
        id=23,
        canonical_url="https://example.com/article",
        url="https://example.com/article",
        google_index_status="technical_issue",
    )
    db = Mock(spec=["get", "execute", "add", "flush", "commit", "refresh"])
    db.get.return_value = SimpleNamespace(
        id=1,
        gsc_property_url="https://example.com/",
        encrypted_gsc_service_account_json="encrypted-test-key",
    )
    db.execute.side_effect = [
        SimpleNamespace(scalar_one_or_none=lambda: None),
        SimpleNamespace(scalars=lambda: [content]),
    ]
    created_jobs: list[IndexingJob] = []
    db.add.side_effect = created_jobs.append

    def fail_dispatch(_job_id: int) -> None:
        raise OSError("worker executable is unavailable")

    service = IndexingService(
        db=db,
        settings=test_settings,
        health_service=Mock(),
        dispatcher=fail_dispatch,
    )

    try:
        service.start(1)
    except ValidationAppError as exc:
        assert "could not be launched" in exc.detail
    else:
        raise AssertionError("Expected worker launch to fail.")

    assert created_jobs[0].status == "failed"
    assert content.google_index_status == "technical_issue"


def test_start_requires_authorized_search_console_property(test_settings: Settings) -> None:
    db = Mock(spec=["get", "execute"])
    db.get.return_value = SimpleNamespace(id=1, gsc_property_url=None)
    service = IndexingService(
        db=db,
        settings=test_settings,
        health_service=Mock(),
        dispatcher=Mock(),
    )

    try:
        service.start(1)
    except ValidationAppError as exc:
        assert "Search Console property" in exc.detail
    else:
        raise AssertionError("Expected indexing to require a Search Console property.")

    db.execute.assert_not_called()


def test_start_requires_service_account_credentials(test_settings: Settings) -> None:
    db = Mock(spec=["get", "execute"])
    db.get.return_value = SimpleNamespace(
        id=1,
        gsc_property_url="https://example.com/",
        encrypted_gsc_service_account_json=None,
    )
    service = IndexingService(
        db=db,
        settings=test_settings.model_copy(update={"google_service_account_json": ""}),
        health_service=Mock(),
        dispatcher=Mock(),
    )

    try:
        service.start(1)
    except ValidationAppError as exc:
        assert "Upload a Google service-account JSON file" in exc.detail
    else:
        raise AssertionError("Expected indexing to require service-account credentials.")

    db.execute.assert_not_called()


def test_access_token_uses_uploaded_service_account_without_live_requests(
    test_settings: Settings,
    monkeypatch: Any,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    account_json = json.dumps({
        "type": "service_account",
        "client_email": "indexer@example-project.iam.gserviceaccount.com",
        "private_key": private_key_pem,
        "token_uri": "https://oauth2.googleapis.com/token",
    })
    requests: list[tuple[str, dict[str, str]]] = []

    def fake_post(url: str, *, data: dict[str, str], timeout: int) -> Mock:
        requests.append((url, data))
        response = Mock()
        response.json.return_value = {"access_token": "mock-index-token"}
        return response

    monkeypatch.setattr("app.services.indexing_service.httpx.post", fake_post)
    service = IndexingService(
        db=Mock(),
        settings=test_settings.model_copy(update={"google_service_account_json": ""}),
        health_service=Mock(),
    )

    token = service._get_access_token(account_json)

    encoded_payload = requests[0][1]["assertion"].split(".")[1]
    decoded_payload = base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
    jwt_payload = json.loads(decoded_payload)
    assert token == "mock-index-token"
    assert requests[0][0] == "https://oauth2.googleapis.com/token"
    assert jwt_payload["iss"] == "indexer@example-project.iam.gserviceaccount.com"
    assert jwt_payload["aud"] == "https://oauth2.googleapis.com/token"


def test_execute_job_uses_health_service_resource_check(test_settings: Settings) -> None:
    job = IndexingJob(
        id=1,
        job_uuid="index-job-1",
        website_id=1,
        status="queued",
        requested_count=0,
        processed_count=0,
        indexed_count=0,
        skipped_count=0,
        ready_count=0,
        failed_count=0,
        progress_count=0,
        content_ids_json=[],
        available_at=datetime(2026, 11, 28),
    )
    db = Mock(spec=["get", "execute", "commit", "refresh"])
    db.get.side_effect = [job, SimpleNamespace(id=1)]
    db.execute.return_value = SimpleNamespace(scalars=lambda: [])
    health_service = Mock(spec=["get_system_resources"])
    health_service.get_system_resources.return_value = SimpleNamespace(
        guardian_status="normal",
    )
    service = IndexingService(
        db=db,
        settings=test_settings,
        health_service=health_service,
    )

    completed = service.execute_job(1)

    assert completed.status == "completed"
    health_service.get_system_resources.assert_called_once_with()
