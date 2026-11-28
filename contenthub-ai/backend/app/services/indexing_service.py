from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT, Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.security import decrypt_secret
from app.models.base import utc_now_naive
from app.models.indexing import IndexingHistory, IndexingJob
from app.models.social_post import SocialPost
from app.models.website import Website
from app.models.website_content import WebsiteContent
from app.services.monitoring.health_service import HealthService


class IndexingService:
    MAX_URLS = 10
    SEARCH_CONSOLE_SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"

    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        health_service: HealthService,
        dispatcher: Any = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.health_service = health_service
        self.dispatcher = dispatcher

    def get_status(self, website_id: int) -> dict[str, Any]:
        job = self.db.execute(
            select(IndexingJob)
            .where(IndexingJob.website_id == website_id)
            .where(IndexingJob.status.in_(("queued", "processing", "deferred")))
            .order_by(IndexingJob.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if job is not None:
            return {
                "state": job.status,
                "progress": job.progress_count,
                "total": job.requested_count,
                "processed": job.processed_count,
                "indexed": job.indexed_count,
                "skipped": job.skipped_count,
                "ready": job.ready_count,
                "failed": job.failed_count,
            }
        latest = self.db.execute(
            select(IndexingJob)
            .where(IndexingJob.website_id == website_id)
            .order_by(IndexingJob.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest is not None:
            return {
                "state": latest.status,
                "progress": latest.progress_count,
                "total": latest.requested_count,
                "processed": latest.processed_count,
                "indexed": latest.indexed_count,
                "skipped": latest.skipped_count,
                "ready": latest.ready_count,
                "failed": latest.failed_count,
            }
        return {
            "state": "idle",
            "progress": 0,
            "total": 0,
            "processed": 0,
            "indexed": 0,
            "skipped": 0,
            "ready": 0,
            "failed": 0,
        }

    def _dispatch_job(self, job_id: int) -> None:
        if self.dispatcher is not None:
            self.dispatcher(job_id)
            return

        log_file = None
        with contextlib.suppress(OSError):
            log_dir = self.settings.resolved_storage_root / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = (log_dir / "indexing-worker.log").open("ab")

        try:
            subprocess.Popen(
                [sys.executable, "-m", "app.cli", "run-indexing-job", "--job-id", str(job_id)],
                cwd=str(BACKEND_ROOT),
                stdout=log_file if log_file is not None else subprocess.DEVNULL,
                stderr=log_file if log_file is not None else subprocess.DEVNULL,
                start_new_session=True,
            )
        finally:
            if log_file is not None:
                with contextlib.suppress(OSError):
                    log_file.close()

    def _website_service_account_json(self, website: Website) -> str | None:
        encrypted = getattr(website, "encrypted_gsc_service_account_json", None)
        if encrypted:
            return decrypt_secret(encrypted, self.settings.app_encryption_key)
        return self.settings.google_service_account_json.strip() or None

    def test_google_account(self, website_id: int) -> dict[str, Any]:
        website = self.db.get(Website, website_id)
        if website is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        property_url = (website.gsc_property_url or "").strip()
        if not property_url:
            raise ValidationAppError(
                "Configure and save the authorized Search Console property before testing."
            )
        service_account_json = self._website_service_account_json(website)
        if not service_account_json:
            raise ValidationAppError(
                "Upload a Google service-account JSON file in Website Settings before testing."
            )

        try:
            account = json.loads(service_account_json)
            if not isinstance(account, dict):
                raise ValueError("Service-account JSON must be an object.")
            account_email = str(account.get("client_email") or "").strip()
            if not account_email:
                raise ValueError("Service-account email is missing.")
            token = self._get_access_token(service_account_json)
            response = httpx.get(
                self.SEARCH_CONSOLE_SITES_URL,
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ValidationAppError(
                f"Google rejected the account test (HTTP {exc.response.status_code})."
            ) from exc
        except (httpx.RequestError, RuntimeError, TypeError, ValueError) as exc:
            raise ValidationAppError(
                "Could not verify the Google service account. "
                "Check the key and network, then retry."
            ) from exc

        entries = payload.get("siteEntry", []) if isinstance(payload, dict) else []
        if not isinstance(entries, list) or not any(
            isinstance(entry, dict) and entry.get("siteUrl") == property_url
            for entry in entries
        ):
            raise ValidationAppError(
                "Google authentication succeeded, but this account cannot access the configured "
                "Search Console property. Add the service-account email as a property user."
            )

        verified_at = utc_now_naive()
        website.gsc_property_verified_at = verified_at
        self.db.commit()
        return {
            "connected": True,
            "account_email": account_email,
            "property_url": property_url,
            "verified_at": verified_at,
        }

    def start(self, website_id: int) -> dict[str, Any]:
        website = self.db.get(Website, website_id)
        if website is None:
            raise NotFoundError(f"Website #{website_id} not found.")
        if not (website.gsc_property_url or "").strip():
            raise ValidationAppError(
                "Configure an authorized Google Search Console property before indexing."
            )
        if not (
            getattr(website, "encrypted_gsc_service_account_json", None)
            or self.settings.google_service_account_json.strip()
        ):
            raise ValidationAppError(
                "Upload a Google service-account JSON file in Website Settings before indexing."
            )
        if not website.gsc_property_verified_at:
            raise ValidationAppError(
                "Test the Google service account against this Search Console property "
                "before indexing."
            )
        active = self.db.execute(
            select(IndexingJob)
            .where(IndexingJob.website_id == website_id)
            .where(IndexingJob.status.in_(("queued", "processing", "deferred")))
            .limit(1)
        ).scalar_one_or_none()
        if active is not None:
            if active.status == "deferred":
                active.status = "queued"
                active.deferred_reason = None
                self.db.commit()
                self._dispatch_job(active.id)
                return self.get_status(website_id)
            raise ConflictError("An indexing job is already active for this website.")

        rows = list(
            self.db.execute(
                select(WebsiteContent)
                .where(WebsiteContent.website_id == website_id)
                .where(WebsiteContent.is_excluded.is_(False))
                .where(WebsiteContent.extraction_status != "failed")
                .where(WebsiteContent.google_index_status != "indexed")
                .where(WebsiteContent.google_index_status.not_in(("queued", "pending")))
                .order_by(
                    WebsiteContent.published_at.desc(),
                    WebsiteContent.google_index_last_attempt_at.asc(),
                    WebsiteContent.first_discovered_at.desc(),
                    WebsiteContent.id.desc(),
                )
            ).scalars()
        )

        selected: list[WebsiteContent] = []
        seen: set[str] = set()
        for row in rows:
            url = (row.canonical_url or row.url or "").strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            if url in seen:
                continue
            seen.add(url)
            selected.append(row)
            if len(selected) == self.MAX_URLS:
                break

        if not selected:
            raise ValidationAppError("No eligible URLs are available for indexing.")

        now = utc_now_naive()
        prior_statuses = {row.id: row.google_index_status for row in selected}
        job = IndexingJob(
            job_uuid=str(uuid.uuid4()),
            website_id=website_id,
            status="queued",
            requested_count=len(selected),
            progress_count=0,
            processed_count=0,
            indexed_count=0,
            skipped_count=0,
            ready_count=0,
            failed_count=0,
            content_ids_json=[row.id for row in selected],
            available_at=now,
        )
        self.db.add(job)
        self.db.flush()
        for row in selected:
            row.google_index_status = "queued"
        self.db.commit()
        self.db.refresh(job)
        try:
            self._dispatch_job(job.id)
        except OSError as exc:
            job.status = "failed"
            job.error_message = f"Worker launch failed: {exc}"[:500]
            for row in selected:
                row.google_index_status = prior_statuses[row.id]
            self.db.commit()
            raise ValidationAppError(
                "The indexing worker could not be launched; the queued URLs were restored."
            ) from exc
        return self.get_status(website_id)

    def run_daily_indexing(self, *, execute_inline: bool = False) -> dict[str, Any]:
        websites = list(
            self.db.execute(
                select(Website).where(Website.status == "active").order_by(Website.id.asc())
            ).scalars()
        )
        if not websites:
            raise ValidationAppError("No active websites are configured for indexing.")

        summary = {
            "state": "idle",
            "progress": 0,
            "total": 0,
            "processed": 0,
            "indexed": 0,
            "skipped": 0,
            "ready": 0,
            "failed": 0,
        }
        started_any = False
        last_error: ValidationAppError | ConflictError | None = None

        for site in websites:
            if execute_inline:
                pending_job = self.db.execute(
                    select(IndexingJob)
                    .where(IndexingJob.website_id == site.id)
                    .where(IndexingJob.status.in_(("queued", "deferred")))
                    .order_by(IndexingJob.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if pending_job is not None:
                    done = self.execute_job(pending_job.id)
                    st = self.get_status(site.id)
                    started_any = True
                    summary["state"] = done.status
                else:
                    orig_dispatcher = self.dispatcher
                    dispatched_ids: list[int] = []
                    self.dispatcher = lambda jid, _ids=dispatched_ids: _ids.append(jid)
                    try:
                        self.start(site.id)
                    except (ValidationAppError, ConflictError) as exc:
                        last_error = exc
                        continue
                    finally:
                        self.dispatcher = orig_dispatcher
                    for jid in dispatched_ids:
                        self.execute_job(jid)
                    st = self.get_status(site.id)
                    started_any = True
            else:
                try:
                    st = self.start(site.id)
                    started_any = True
                except (ValidationAppError, ConflictError) as exc:
                    last_error = exc
                    st = self.get_status(site.id)

            if st["state"] in {"queued", "processing"} or (
                summary["state"] == "idle" and st["state"] != "idle"
            ):
                summary["state"] = st["state"]
            for key in ("progress", "total", "processed", "indexed", "skipped", "ready", "failed"):
                summary[key] += int(st.get(key, 0))

        if not started_any and last_error is not None and not execute_inline:
            raise last_error
        return summary

    def _property_authorizes(self, website: Website, url: str) -> bool:
        property_url = (website.gsc_property_url or "").strip()
        if not property_url:
            return False
        if property_url.startswith("sc-domain:"):
            domain = property_url.removeprefix("sc-domain:")
            host = urlparse(url).hostname or ""
            return host == domain or host.endswith("." + domain)
        base = property_url.rstrip("/") + "/"
        return url.startswith(base)

    def _get_access_token(self, service_account_json: str | None = None) -> str:
        raw = (
            (service_account_json or "").strip()
            or self.settings.google_service_account_json.strip()
        )
        if not raw:
            raise RuntimeError("Google service-account credentials are not configured.")
        try:
            account = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Google service-account JSON is invalid.") from exc
        if not isinstance(account, dict):
            raise RuntimeError("Google service-account JSON must be an object.")
        key_data = account.get("private_key")
        client_email = account.get("client_email")
        token_uri = account.get("token_uri") or "https://oauth2.googleapis.com/token"
        if not key_data or not client_email:
            raise RuntimeError("Google service-account JSON is incomplete.")
        if token_uri != "https://oauth2.googleapis.com/token":
            raise RuntimeError("Google service-account token_uri is not supported.")

        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iss": client_email,
            "scope": "https://www.googleapis.com/auth/webmasters.readonly",
            "aud": token_uri,
            "iat": now,
            "exp": now + 3600,
        }
        import base64

        def enc(value: dict[str, Any]) -> str:
            body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
            return base64.urlsafe_b64encode(body).rstrip(b"=").decode()

        signing_input = f"{enc(header)}.{enc(payload)}"
        key = serialization.load_pem_private_key(key_data.encode(), password=None)
        signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        jwt = f"{signing_input}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"
        response = httpx.post(
            token_uri,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt},
            timeout=30,
        )
        response.raise_for_status()
        token = str(response.json().get("access_token") or "").strip()
        if not token:
            raise RuntimeError("Google OAuth token response did not include access_token.")
        return token

    def _inspect_url(
        self,
        site_url: str,
        inspection_url: str,
        service_account_json: str | None = None,
    ) -> dict[str, Any]:
        token = self._get_access_token(service_account_json)
        response = httpx.post(
            "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"inspectionUrl": inspection_url, "siteUrl": site_url},
            timeout=45,
        )
        response.raise_for_status()
        return response.json()

    def _technical_check(self, url: str) -> dict[str, Any]:
        try:
            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=20,
                headers={"User-Agent": "ContentHubAI/4.1 TechnicalIndexCheck"},
            )
        except httpx.HTTPError as exc:
            return {"status": "failed", "http_status": None, "error": str(exc)[:500]}
        soup = BeautifulSoup(response.text, "html.parser")
        robots = soup.find("meta", attrs={"name": "robots"})
        robots_content = str(robots.get("content") or "").lower() if robots else ""
        canonical = soup.find("link", attrs={"rel": "canonical"})
        canonical_url = str(canonical.get("href") or "").strip() if canonical else ""
        blocked = "noindex" in robots_content
        return {
            "status": "ready" if response.status_code == 200 and not blocked else "blocked",
            "http_status": response.status_code,
            "robots": robots_content or None,
            "canonical_url": canonical_url or None,
            "noindex": blocked,
        }

    def execute_job(self, job_id: int) -> IndexingJob:
        job = self.db.get(IndexingJob, job_id)
        if job is None:
            raise NotFoundError(f"Indexing job #{job_id} not found.")
        if job.status not in {"queued", "deferred"}:
            return job
        guardian = self.health_service.get_system_resources()
        if guardian.guardian_status == "critical":
            job.status = "deferred"
            job.deferred_reason = "Resource Guardian critical pressure."
            self.db.commit()
            return job

        job.status = "processing"
        job.started_at = utc_now_naive()
        job.heartbeat_at = utc_now_naive()
        self.db.commit()
        website = self.db.get(Website, job.website_id)
        if website is None:
            job.status = "failed"
            job.error_message = "Website no longer exists."
            self.db.commit()
            return job

        for content_id in job.content_ids_json:
            content = self.db.get(WebsiteContent, content_id)
            if content is None:
                job.failed_count += 1
                job.progress_count += 1
                continue
            url = (content.canonical_url or content.url or "").strip()
            if content.google_index_status == "indexed":
                job.skipped_count += 1
                job.progress_count += 1
                job.processed_count += 1
                continue
            now = utc_now_naive()
            content.google_index_last_attempt_at = now

            if not self._property_authorizes(website, url):
                content.google_index_status = "unsupported_property"
                job.skipped_count += 1
                job.progress_count += 1
                job.processed_count += 1
                self.db.add(
                    IndexingHistory(
                        job_id=job.id,
                        website_id=job.website_id,
                        website_content_id=content.id,
                        url=url,
                        outcome="skipped",
                        inspection_status="unsupported_property",
                        technical_status="not_checked",
                        details_json={
                            "reason": ("URL is outside the configured authorized GSC property.")
                        },
                    )
                )
                self.db.commit()
                continue

            technical = self._technical_check(url)
            inspection: dict[str, Any] | None = None
            try:
                service_account_json = self._website_service_account_json(website)
                inspection = self._inspect_url(
                    website.gsc_property_url or "",
                    url,
                    service_account_json,
                )
            except Exception as exc:
                content.google_index_status = "failed"
                job.failed_count += 1
                job.progress_count += 1
                job.processed_count += 1
                self.db.add(
                    IndexingHistory(
                        job_id=job.id,
                        website_id=job.website_id,
                        website_content_id=content.id,
                        url=url,
                        outcome="failed",
                        inspection_status="inspection_error",
                        technical_status=technical["status"],
                        details_json=technical,
                        error_message=str(exc)[:500],
                    )
                )
                self.db.commit()
                continue

            index_result = (inspection.get("inspectionResult") or {}).get("indexStatusResult") or {}
            verdict = str(index_result.get("verdict") or "").strip()
            coverage = str(index_result.get("coverageState") or "").strip()
            content.google_index_verdict = verdict
            content.google_index_coverage_state = coverage
            content.google_index_inspection_json = inspection

            verdict_pass = verdict.upper() == "PASS"
            coverage_indexed = "indexed" in coverage.lower()
            if verdict_pass and coverage_indexed:
                content.google_index_status = "indexed"
                content.google_index_verified_at = now
                job.indexed_count += 1
                outcome = "indexed"
            elif technical["status"] == "ready":
                content.google_index_status = "ready_to_request"
                job.ready_count += 1
                outcome = "ready"
            else:
                content.google_index_status = "technical_issue"
                job.failed_count += 1
                outcome = "failed"

            job.progress_count += 1
            job.processed_count += 1
            self.db.add(
                IndexingHistory(
                    job_id=job.id,
                    website_id=job.website_id,
                    website_content_id=content.id,
                    url=url,
                    outcome=outcome,
                    inspection_status=coverage or verdict or "unknown",
                    technical_status=technical["status"],
                    details_json={
                        "technical": technical,
                        "inspection": {
                            "verdict": verdict,
                            "coverageState": coverage,
                        },
                        "request_confirmed": False,
                    },
                )
            )
            job.heartbeat_at = utc_now_naive()
            self.db.commit()

        self._verify_published_backlinks(job.website_id)
        job.status = "completed"
        job.completed_at = utc_now_naive()
        self.db.commit()
        self.db.refresh(job)
        return job

    def _verify_published_backlinks(self, website_id: int) -> None:
        posts = list(
            self.db.execute(
                select(SocialPost)
                .where(SocialPost.website_id == website_id)
                .where(SocialPost.published_url.is_not(None))
                .where(SocialPost.backlink_status != "found")
            ).scalars()
        )
        for post in posts:
            source = (post.target_url_with_utm or post.source_url or "").strip()
            permalink = (post.published_url or "").strip()
            if not source or not permalink:
                continue
            try:
                response = httpx.get(permalink, follow_redirects=True, timeout=20)
                found = source.lower() in response.text.lower()
                post.backlink_status = "found" if found else "missing"
            except httpx.HTTPError:
                post.backlink_status = "check_failed"
            post.backlink_checked_at = utc_now_naive()
        self.db.commit()
