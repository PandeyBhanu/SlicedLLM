import uuid
from typing import List
from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_prompt_service
from app.schemas.prompt import (
    PromptCreate,
    PromptDiffResponse,
    PromptResponse,
    PromptRollbackRequest,
    PromptVersionCreate,
    PromptVersionResponse,
)
from app.services.prompt import PromptService

router = APIRouter()


@router.post("/", response_model=PromptResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt(
    schema: PromptCreate,
    service: PromptService = Depends(get_prompt_service),
):
    """Create a new prompt name container."""
    return await service.create_prompt(schema)


@router.get("/", response_model=List[PromptResponse])
async def list_prompts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    service: PromptService = Depends(get_prompt_service),
):
    """Retrieve all prompts."""
    return await service.get_all_prompts(skip=skip, limit=limit)


@router.get("/{id}", response_model=PromptResponse)
async def get_prompt(
    id: uuid.UUID,
    service: PromptService = Depends(get_prompt_service),
):
    """Retrieve a single prompt and all associated historical versions."""
    return await service.get_prompt(id)


@router.post("/{id}/versions", response_model=PromptVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt_version(
    id: uuid.UUID,
    schema: PromptVersionCreate,
    service: PromptService = Depends(get_prompt_service),
):
    """Publish a new immutable version of a prompt template."""
    return await service.create_prompt_version(prompt_id=id, schema=schema)


@router.post("/{id}/rollback", response_model=PromptVersionResponse)
async def rollback_prompt_version(
    id: uuid.UUID,
    schema: PromptRollbackRequest,
    service: PromptService = Depends(get_prompt_service),
):
    """Switch active production status to a former prompt version without deleting history."""
    return await service.rollback_prompt_version(
        prompt_id=id, target_version_id=schema.target_version_id
    )


@router.get("/{id}/diff", response_model=PromptDiffResponse)
async def get_prompt_diff(
    id: uuid.UUID,
    version_a_id: uuid.UUID = Query(..., description="First version to compare"),
    version_b_id: uuid.UUID = Query(..., description="Second version to compare"),
    service: PromptService = Depends(get_prompt_service),
):
    """Generate line-by-line unified prompt diffs and metadata parameter diffs."""
    return await service.get_prompt_diff(
        prompt_id=id, version_a_id=version_a_id, version_b_id=version_b_id
    )
