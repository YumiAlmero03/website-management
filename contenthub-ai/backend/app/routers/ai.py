from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request, Response, status

from app.core.dependencies import (
    extract_client_ip,
    get_ai_generation_service,
    get_ai_management_service,
    get_knowledge_profile_service,
    get_prompt_manager_service,
    require_admin,
    require_csrf,
)
from app.schemas.ai import (
    AiGenerationJobListResponse,
    AiGenerationJobResponse,
    AiGenerationLogListResponse,
    AiProviderCreateRequest,
    AiProviderModelsResponse,
    AiProviderResponse,
    AiProviderTestRequest,
    AiProviderTestResponse,
    AiProviderUpdateRequest,
    AiUsageSummaryResponse,
    CacheInvalidateRequest,
    CacheStatsResponse,
    KnowledgeProfileGenerateRequest,
    KnowledgeProfileResponse,
    KnowledgeProfileRevisionResponse,
    KnowledgeProfileUpdateRequest,
    PromptPreviewRequest,
    PromptPreviewResponse,
    PromptTemplateCreateRequest,
    PromptTemplateResponse,
    PromptTemplateRevisionResponse,
    PromptTemplateUpdateRequest,
)
from app.schemas.common import MessageResponse
from app.services.ai.generation_service import AiGenerationService
from app.services.ai.knowledge_service import KnowledgeProfileService
from app.services.ai.management_service import AiManagementService
from app.services.ai.prompt_service import PromptManagerService
from app.services.auth_service import AuthenticatedSession

router = APIRouter(tags=["Gemini AI Engine"])


# ==============================================================================
# Gemini Provider Configuration, Connection Testing & Model Selection
# ==============================================================================
@router.get("/ai/providers", response_model=list[AiProviderResponse])
def list_ai_providers(
    response: Response,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[AiManagementService, Depends(get_ai_management_service)],
) -> list[AiProviderResponse]:
    response.headers["Cache-Control"] = "no-store"
    return service.list_providers()


@router.post(
    "/ai/providers",
    response_model=AiProviderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_ai_provider(
    payload: AiProviderCreateRequest,
    request: Request,
    response: Response,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[AiManagementService, Depends(get_ai_management_service)],
) -> AiProviderResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.create_provider(
        payload, user_id=admin.user.id, ip_address=extract_client_ip(request)
    )


@router.patch("/ai/providers/{provider_id}", response_model=AiProviderResponse)
def update_ai_provider(
    provider_id: int,
    payload: AiProviderUpdateRequest,
    request: Request,
    response: Response,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[AiManagementService, Depends(get_ai_management_service)],
) -> AiProviderResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.update_provider(
        provider_id, payload, user_id=admin.user.id, ip_address=extract_client_ip(request)
    )


@router.post("/ai/providers/{provider_id}/test", response_model=AiProviderTestResponse)
def test_ai_provider(
    provider_id: int,
    request: Request,
    response: Response,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[AiManagementService, Depends(get_ai_management_service)],
    payload: Annotated[AiProviderTestRequest | None, Body()] = None,
) -> AiProviderTestResponse:
    response.headers["Cache-Control"] = "no-store"
    req = payload or AiProviderTestRequest()
    return service.test_provider(
        provider_id,
        verify_generation=req.verify_generation,
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )


@router.get("/ai/providers/{provider_id}/models", response_model=AiProviderModelsResponse)
def list_ai_provider_models(
    provider_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[AiManagementService, Depends(get_ai_management_service)],
    refresh: bool = Query(default=True),
) -> AiProviderModelsResponse:
    return service.list_provider_models(provider_id, refresh=refresh)


# ==============================================================================
# Website Knowledge Profile
# ==============================================================================
@router.get("/websites/{website_id}/knowledge-profile", response_model=KnowledgeProfileResponse)
def get_website_knowledge_profile(
    website_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[KnowledgeProfileService, Depends(get_knowledge_profile_service)],
) -> KnowledgeProfileResponse:
    return service.get_profile(website_id)


@router.patch("/websites/{website_id}/knowledge-profile", response_model=KnowledgeProfileResponse)
def update_website_knowledge_profile(
    website_id: int,
    payload: KnowledgeProfileUpdateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[KnowledgeProfileService, Depends(get_knowledge_profile_service)],
) -> KnowledgeProfileResponse:
    return service.update_profile(
        website_id, payload, user_id=admin.user.id, ip_address=extract_client_ip(request)
    )


@router.post(
    "/websites/{website_id}/knowledge-profile/generate",
    response_model=KnowledgeProfileResponse,
)
def generate_website_knowledge_profile(
    website_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[KnowledgeProfileService, Depends(get_knowledge_profile_service)],
    payload: Annotated[KnowledgeProfileGenerateRequest | None, Body()] = None,
) -> KnowledgeProfileResponse:
    req = payload or KnowledgeProfileGenerateRequest()
    return service.generate_profile(
        website_id, req, user_id=admin.user.id, ip_address=extract_client_ip(request)
    )


@router.get(
    "/websites/{website_id}/knowledge-profile/revisions",
    response_model=list[KnowledgeProfileRevisionResponse],
)
def list_website_knowledge_revisions(
    website_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[KnowledgeProfileService, Depends(get_knowledge_profile_service)],
) -> list[KnowledgeProfileRevisionResponse]:
    return service.list_revisions(website_id)


# ==============================================================================
# Prompt Manager
# ==============================================================================
@router.get("/ai/prompts", response_model=list[PromptTemplateResponse])
def list_prompts(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[PromptManagerService, Depends(get_prompt_manager_service)],
    task_type: str | None = Query(default=None, max_length=64),
    website_id: int | None = Query(default=None, ge=1),
    social_profile_id: int | None = Query(default=None, ge=1),
) -> list[PromptTemplateResponse]:
    return service.list_prompts(
        task_type=task_type, website_id=website_id, social_profile_id=social_profile_id
    )


@router.post(
    "/ai/prompts",
    response_model=PromptTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_prompt(
    payload: PromptTemplateCreateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[PromptManagerService, Depends(get_prompt_manager_service)],
) -> PromptTemplateResponse:
    return service.create_prompt(
        payload, user_id=admin.user.id, ip_address=extract_client_ip(request)
    )


@router.patch("/ai/prompts/{prompt_id}", response_model=PromptTemplateResponse)
def update_prompt(
    prompt_id: int,
    payload: PromptTemplateUpdateRequest,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[PromptManagerService, Depends(get_prompt_manager_service)],
) -> PromptTemplateResponse:
    return service.update_prompt(
        prompt_id, payload, user_id=admin.user.id, ip_address=extract_client_ip(request)
    )


@router.post("/ai/prompts/{prompt_id}/preview", response_model=PromptPreviewResponse)
def preview_prompt(
    prompt_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[PromptManagerService, Depends(get_prompt_manager_service)],
    payload: Annotated[PromptPreviewRequest | None, Body()] = None,
) -> PromptPreviewResponse:
    return service.preview_prompt(prompt_id, payload or PromptPreviewRequest())


@router.get(
    "/ai/prompts/{prompt_id}/revisions",
    response_model=list[PromptTemplateRevisionResponse],
)
def list_prompt_revisions(
    prompt_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[PromptManagerService, Depends(get_prompt_manager_service)],
) -> list[PromptTemplateRevisionResponse]:
    return service.list_revisions(prompt_id)


# ==============================================================================
# Background AI Generation Jobs, Usage, History & Cache
# ==============================================================================
@router.get("/ai/jobs", response_model=AiGenerationJobListResponse)
def list_ai_jobs(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[AiGenerationService, Depends(get_ai_generation_service)],
    website_id: int | None = Query(default=None, ge=1),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> AiGenerationJobListResponse:
    return service.list_jobs(
        website_id=website_id, status=status_filter, page=page, page_size=page_size
    )


@router.get("/ai/jobs/{job_id}", response_model=AiGenerationJobResponse)
def get_ai_job(
    job_id: int,
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[AiGenerationService, Depends(get_ai_generation_service)],
) -> AiGenerationJobResponse:
    return service.get_job(job_id)


@router.post(
    "/ai/jobs/{job_id}/retry",
    response_model=AiGenerationJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_ai_job(
    job_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[AiGenerationService, Depends(get_ai_generation_service)],
) -> AiGenerationJobResponse:
    return service.retry_job(
        job_id, user_id=admin.user.id, ip_address=extract_client_ip(request)
    )


@router.post("/ai/jobs/{job_id}/cancel", response_model=AiGenerationJobResponse)
def cancel_ai_job(
    job_id: int,
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[AiGenerationService, Depends(get_ai_generation_service)],
) -> AiGenerationJobResponse:
    return service.cancel_job(
        job_id, user_id=admin.user.id, ip_address=extract_client_ip(request)
    )


@router.get("/ai/usage", response_model=AiUsageSummaryResponse)
def get_ai_usage(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[AiManagementService, Depends(get_ai_management_service)],
) -> AiUsageSummaryResponse:
    return service.get_usage_summary()


@router.get("/ai/history", response_model=AiGenerationLogListResponse)
def list_ai_history(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[AiManagementService, Depends(get_ai_management_service)],
    website_id: int | None = Query(default=None, ge=1),
    provider_id: int | None = Query(default=None, ge=1),
    task_type: str | None = Query(default=None, max_length=64),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> AiGenerationLogListResponse:
    return service.list_history(
        website_id=website_id,
        provider_id=provider_id,
        task_type=task_type,
        status=status_filter,
        page=page,
        page_size=page_size,
    )


@router.get("/ai/history/export")
def export_ai_history_csv(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[AiManagementService, Depends(get_ai_management_service)],
    website_id: int | None = Query(default=None, ge=1),
    provider_id: int | None = Query(default=None, ge=1),
    task_type: str | None = Query(default=None, max_length=64),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
) -> Response:
    csv_text = service.export_history_csv(
        website_id=website_id,
        provider_id=provider_id,
        task_type=task_type,
        status=status_filter,
    )
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="contenthub-ai-history.csv"'},
    )


@router.get("/ai/cache/stats", response_model=CacheStatsResponse)
def get_ai_cache_stats(
    _admin: Annotated[AuthenticatedSession, Depends(require_admin)],
    service: Annotated[AiManagementService, Depends(get_ai_management_service)],
    website_id: int | None = Query(default=None, ge=1),
) -> CacheStatsResponse:
    return service.get_cache_stats(website_id=website_id)


@router.post("/ai/cache/invalidate", response_model=MessageResponse)
def invalidate_ai_cache(
    request: Request,
    admin: Annotated[AuthenticatedSession, Depends(require_csrf)],
    service: Annotated[AiManagementService, Depends(get_ai_management_service)],
    payload: Annotated[CacheInvalidateRequest | None, Body()] = None,
) -> MessageResponse:
    removed = service.invalidate_cache(
        payload or CacheInvalidateRequest(),
        user_id=admin.user.id,
        ip_address=extract_client_ip(request),
    )
    return MessageResponse(message=f"Cleared {removed} cached response(s).")
