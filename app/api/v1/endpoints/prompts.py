import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_prompt_service
from app.schemas.audit import AuditLogResponse
from app.schemas.prompt import (
    ChangelogEntry,
    PromptCreate,
    PromptDetailResponse,
    PromptDiffResponse,
    PromptResponse,
    PromptRollbackRequest,
    PromptSummaryResponse,
    PromptUpdate,
    PromptVersionCreate,
    PromptVersionResponse,
    VersionIntegrityResponse,
)
from app.services.prompt import PromptService

router = APIRouter()


@router.post("", response_model=PromptResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt(schema: PromptCreate, service: PromptService = Depends(get_prompt_service)):
    return await service.create_prompt(schema)


@router.get("", response_model=list[PromptSummaryResponse])
async def list_prompts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    service: PromptService = Depends(get_prompt_service),
):
    rows = await service.list_prompts(skip=skip, limit=limit)
    return [
        PromptSummaryResponse.model_validate(
            {
                **PromptResponse.model_validate(r["prompt"]).model_dump(),
                "version_count": r["version_count"],
                "active_version": r["active_version"],
                "active_version_id": r["active_version_id"],
                "latest_version": r["latest_version"],
            }
        )
        for r in rows
    ]


@router.get("/{id}", response_model=PromptDetailResponse)
async def get_prompt(id: uuid.UUID, service: PromptService = Depends(get_prompt_service)):
    data = await service.get_prompt_with_versions(id)
    return PromptDetailResponse.model_validate(
        {
            **PromptResponse.model_validate(data["prompt"]).model_dump(),
            "versions": [PromptVersionResponse.model_validate(v) for v in data["versions"]],
        }
    )


@router.patch("/{id}", response_model=PromptResponse)
async def update_prompt(
    id: uuid.UUID, schema: PromptUpdate, service: PromptService = Depends(get_prompt_service)
):
    """Update description/tags. Names and version content are not editable."""
    return await service.update_prompt(id, schema)


@router.post(
    "/{id}/versions", response_model=PromptVersionResponse, status_code=status.HTTP_201_CREATED
)
async def create_prompt_version(
    id: uuid.UUID, schema: PromptVersionCreate, service: PromptService = Depends(get_prompt_service)
):
    """Publish a new immutable version."""
    return await service.create_prompt_version(prompt_id=id, schema=schema)


@router.get("/{id}/versions", response_model=list[PromptVersionResponse])
async def list_versions(id: uuid.UUID, service: PromptService = Depends(get_prompt_service)):
    return await service.list_versions(id)


@router.get("/{id}/versions/{version_id}", response_model=PromptVersionResponse)
async def get_version(
    id: uuid.UUID, version_id: uuid.UUID, service: PromptService = Depends(get_prompt_service)
):
    return await service.get_version(id, version_id)


@router.get("/{id}/versions/{version_id}/integrity", response_model=VersionIntegrityResponse)
async def verify_version_integrity(
    id: uuid.UUID, version_id: uuid.UUID, service: PromptService = Depends(get_prompt_service)
):
    """Recompute the content hash and compare it with the stored one (tamper check)."""
    return await service.verify_version_integrity(id, version_id)


@router.post("/{id}/versions/{version_id}/activate", response_model=PromptVersionResponse)
async def activate_version(
    id: uuid.UUID, version_id: uuid.UUID, service: PromptService = Depends(get_prompt_service)
):
    return await service.activate_version(id, version_id)


@router.post("/{id}/rollback", response_model=PromptVersionResponse)
async def rollback_prompt_version(
    id: uuid.UUID,
    schema: PromptRollbackRequest,
    service: PromptService = Depends(get_prompt_service),
):
    """Re-activate an earlier version; the history is never rewritten."""
    return await service.rollback_prompt_version(id, schema.target_version_id)


@router.get("/{id}/diff", response_model=PromptDiffResponse)
async def get_prompt_diff(
    id: uuid.UUID,
    version_a_id: uuid.UUID = Query(...),
    version_b_id: uuid.UUID = Query(...),
    granularity: str = Query("token", pattern="^(token|line|char)$"),
    tokenizer: str | None = Query(None, description="tiktoken encoding, e.g. o200k_base"),
    model: str | None = Query(None, description="Select the tokenizer for this model"),
    provider: str | None = Query(None),
    service: PromptService = Depends(get_prompt_service),
):
    return await service.get_prompt_diff(
        id,
        version_a_id,
        version_b_id,
        granularity=granularity,
        tokenizer=tokenizer,
        model=model,
        provider=provider,
    )


@router.get("/{id}/changelog", response_model=list[ChangelogEntry])
async def get_changelog(id: uuid.UUID, service: PromptService = Depends(get_prompt_service)):
    return await service.get_changelog(id)


@router.get("/{id}/audit", response_model=list[AuditLogResponse])
async def get_prompt_audit(
    id: uuid.UUID,
    limit: int = Query(200, ge=1, le=1000),
    service: PromptService = Depends(get_prompt_service),
):
    return await service.get_audit_history(id, limit=limit)
