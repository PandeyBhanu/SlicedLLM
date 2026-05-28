import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_db
from app.promptops.activation import ActivationManager
from app.promptops.audit import PromptOpsAuditService
from app.promptops.changelog import ChangelogService
from app.promptops.diff import PromptDiffEngine
from app.promptops.provider_config import ProviderConfigManager
from app.promptops.registry import PromptRegistry
from app.promptops.version_manager import VersionManager
from app.promptops.versioning import validate_semantic_version
from app.schemas.promptops import (
    ActivationHistoryEntry,
    AuditLogEntry,
    ChangelogEntry,
    ChangeSummary,
    DiffResult,
    NextVersionSuggestion,
    PromptCreate,
    PromptStatisticsResponse,
    PromptTagsAdd,
    PromptTagsRemove,
    PromptTagsUpdate,
    PromptUpdate,
    PromptWithVersionsResponse,
    ProviderConfigCreate,
    ProviderConfigResponse,
    ProviderSchema,
    RollbackCandidate,
    RollbackRequest,
    VersionComparisonResponse,
    VersionCreate,
    VersionHistoryEntry,
    VersionResponse,
    VersionValidationResponse,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


# Prompt Registry Endpoints
@router.post("/prompts", response_model=PromptWithVersionsResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt(
    schema: PromptCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new prompt with optional tags."""
    registry = PromptRegistry(db)
    prompt = await registry.create_prompt(
        name=schema.name,
        description=schema.description,
        tags=schema.tags,
    )
    return prompt


@router.put("/prompts/{prompt_id}", response_model=PromptWithVersionsResponse)
async def update_prompt(
    prompt_id: str,
    schema: PromptUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update prompt metadata (not versions)."""
    registry = PromptRegistry(db)
    prompt = await registry.update_prompt(
        prompt_id=prompt_id,
        name=schema.name,
        description=schema.description,
        tags=schema.tags,
    )
    return prompt


@router.put("/prompts/{prompt_id}/tags", response_model=PromptWithVersionsResponse)
async def update_prompt_tags(
    prompt_id: str,
    schema: PromptTagsUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Set tags for a prompt."""
    registry = PromptRegistry(db)
    prompt = await registry.update_prompt(prompt_id=prompt_id, tags=schema.tags)
    return prompt


@router.post("/prompts/{prompt_id}/tags/add", response_model=PromptWithVersionsResponse)
async def add_prompt_tags(
    prompt_id: str,
    schema: PromptTagsAdd,
    db: AsyncSession = Depends(get_db),
):
    """Add tags to a prompt."""
    registry = PromptRegistry(db)
    prompt = await registry.add_tags(prompt_id=prompt_id, tags=schema.tags)
    return prompt


@router.post("/prompts/{prompt_id}/tags/remove", response_model=PromptWithVersionsResponse)
async def remove_prompt_tags(
    prompt_id: str,
    schema: PromptTagsRemove,
    db: AsyncSession = Depends(get_db),
):
    """Remove tags from a prompt."""
    registry = PromptRegistry(db)
    prompt = await registry.remove_tags(prompt_id=prompt_id, tags=schema.tags)
    return prompt


@router.get("/prompts/search/tags", response_model=List[PromptWithVersionsResponse])
async def search_prompts_by_tags(
    tags: List[str] = Query(..., description="Tags to search for"),
    match_all: bool = Query(False, description="Require all tags to match"),
    db: AsyncSession = Depends(get_db),
):
    """Search prompts by tags."""
    registry = PromptRegistry(db)
    prompts = await registry.search_by_tags(tags, match_all=match_all)
    return prompts


@router.get("/prompts/tags", response_model=List[str])
async def get_all_tags(db: AsyncSession = Depends(get_db)):
    """Get all unique tags across all prompts."""
    registry = PromptRegistry(db)
    tags = await registry.get_all_tags()
    return tags


@router.get("/prompts/{prompt_id}/statistics", response_model=PromptStatisticsResponse)
async def get_prompt_statistics(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get statistics for a prompt."""
    registry = PromptRegistry(db)
    stats = await registry.get_prompt_statistics(prompt_id)
    return stats


# Version Management Endpoints
@router.post("/prompts/{prompt_id}/versions", response_model=VersionResponse, status_code=status.HTTP_201_CREATED)
async def create_version(
    prompt_id: str,
    schema: VersionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new immutable prompt version."""
    version_manager = VersionManager(db)
    version = await version_manager.create_version(
        prompt_id=prompt_id,
        semantic_version=schema.semantic_version,
        template=schema.template,
        metadata=schema.metadata,
        provider_config=schema.provider_config,
        set_as_active=schema.set_as_active,
    )
    return version


@router.get("/prompts/{prompt_id}/versions", response_model=List[VersionResponse])
async def list_versions(
    prompt_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all versions of a prompt."""
    version_manager = VersionManager(db)
    versions = await version_manager.list_versions(prompt_id, skip=skip, limit=limit)
    return versions


@router.get("/prompts/{prompt_id}/versions/history", response_model=List[VersionHistoryEntry])
async def get_version_history(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the complete version history for a prompt."""
    version_manager = VersionManager(db)
    history = await version_manager.get_version_history(prompt_id)
    return history


@router.get("/prompts/{prompt_id}/versions/active", response_model=Optional[VersionResponse])
async def get_active_version(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the active version of a prompt."""
    version_manager = VersionManager(db)
    version = await version_manager.get_active_version(prompt_id)
    return version


@router.get("/prompts/{prompt_id}/versions/suggest", response_model=NextVersionSuggestion)
async def suggest_next_version(
    prompt_id: str,
    change_type: str = Query("patch", description="Type of change: major, minor, or patch"),
    db: AsyncSession = Depends(get_db),
):
    """Suggest the next semantic version for a prompt."""
    version_manager = VersionManager(db)
    suggested = await version_manager.suggest_next_version(prompt_id, change_type)
    return NextVersionSuggestion(
        current_version="current",  # Would need to fetch current
        suggested_version=suggested,
        change_type=change_type,
    )


@router.get("/versions/{version_a_id}/compare/{version_b_id}", response_model=VersionComparisonResponse)
async def compare_versions(
    version_a_id: str,
    version_b_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Compare two versions and return their differences."""
    version_manager = VersionManager(db)
    comparison = await version_manager.compare_versions(version_a_id, version_b_id)
    return comparison


@router.post("/versions/validate", response_model=VersionValidationResponse)
async def validate_version(
    version_string: str = Query(..., description="Semantic version string to validate"),
):
    """Validate a semantic version string."""
    is_valid, error_msg = validate_semantic_version(version_string)
    return VersionValidationResponse(is_valid=is_valid, error_message=error_msg)


# Activation and Rollback Endpoints
@router.post("/versions/{version_id}/activate", response_model=VersionResponse)
async def activate_version(
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Activate a specific prompt version."""
    activation_manager = ActivationManager(db)
    version = await activation_manager.activate_version(version_id)
    return version


@router.post("/prompts/{prompt_id}/rollback", response_model=VersionResponse)
async def rollback_prompt(
    prompt_id: str,
    schema: RollbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """Rollback a prompt to a specific version."""
    activation_manager = ActivationManager(db)
    
    if schema.semantic_version:
        version = await activation_manager.rollback_to_semantic_version(
            prompt_id=prompt_id,
            semantic_version=schema.semantic_version,
        )
    elif schema.version_id:
        version = await activation_manager.rollback_to_version(
            version_id=str(schema.version_id),
        )
    else:
        raise ValueError("Either version_id or semantic_version must be provided")
    
    return version


@router.get("/prompts/{prompt_id}/rollback/candidates", response_model=List[RollbackCandidate])
async def get_rollback_candidates(
    prompt_id: str,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Get candidates for rollback (previous versions)."""
    activation_manager = ActivationManager(db)
    candidates = await activation_manager.get_rollback_candidates(prompt_id, limit=limit)
    return candidates


@router.get("/prompts/{prompt_id}/activation/history", response_model=List[ActivationHistoryEntry])
async def get_activation_history(
    prompt_id: str,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get the activation history for a prompt."""
    activation_manager = ActivationManager(db)
    history = await activation_manager.get_activation_history(prompt_id, limit=limit)
    return history


# Changelog Endpoints
@router.get("/prompts/{prompt_id}/changelog", response_model=List[ChangelogEntry])
async def get_changelog(
    prompt_id: str,
    include_diffs: bool = Query(True, description="Include diff information"),
    db: AsyncSession = Depends(get_db),
):
    """Generate a changelog for a prompt."""
    changelog_service = ChangelogService(db)
    changelog = await changelog_service.generate_changelog(prompt_id, include_diffs=include_diffs)
    return changelog


@router.get("/versions/{version_a_id}/diff/{version_b_id}", response_model=Dict[str, Any])
async def get_version_diff(
    version_a_id: str,
    version_b_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a detailed diff between two versions."""
    changelog_service = ChangelogService(db)
    diff = await changelog_service.get_version_diff(version_a_id, version_b_id)
    return diff


@router.get("/prompts/{prompt_id}/changelog/latest", response_model=List[ChangelogEntry])
async def get_latest_changes(
    prompt_id: str,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Get the latest changes for a prompt."""
    changelog_service = ChangelogService(db)
    changes = await changelog_service.get_latest_changes(prompt_id, limit=limit)
    return changes


@router.get("/prompts/{prompt_id}/changelog/summary", response_model=ChangeSummary)
async def get_change_summary(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a summary of changes for a prompt."""
    changelog_service = ChangelogService(db)
    summary = await changelog_service.get_change_summary(prompt_id)
    return summary


# Audit History Endpoints
@router.get("/prompts/{prompt_id}/audit", response_model=List[AuditLogEntry])
async def get_prompt_audit_history(
    prompt_id: str,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Get complete audit history for a prompt."""
    audit_service = PromptOpsAuditService(db)
    history = await audit_service.get_prompt_audit_history(uuid.UUID(prompt_id), limit=limit)
    return history


@router.get("/versions/{version_id}/audit", response_model=List[AuditLogEntry])
async def get_version_audit_history(
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get audit history for a specific version."""
    audit_service = PromptOpsAuditService(db)
    history = await audit_service.get_version_audit_history(uuid.UUID(version_id))
    return history


# Provider Configuration Endpoints
@router.post("/versions/{version_id}/provider-config", response_model=VersionResponse)
async def set_version_provider_config(
    version_id: str,
    schema: ProviderConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    """Set the provider configuration for a specific version."""
    config_manager = ProviderConfigManager(db)
    version = await config_manager.set_version_provider_config(
        version_id=version_id,
        provider=schema.provider,
        config=schema.config,
    )
    return version


@router.get("/versions/{version_id}/provider-config", response_model=ProviderConfigResponse)
async def get_version_provider_config(
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the provider configuration for a specific version."""
    config_manager = ProviderConfigManager(db)
    config = await config_manager.get_version_provider_config(version_id)
    return ProviderConfigResponse(**config)


@router.get("/providers/supported", response_model=List[str])
async def list_supported_providers(db: AsyncSession = Depends(get_db)):
    """List all supported providers."""
    config_manager = ProviderConfigManager(db)
    providers = await config_manager.list_supported_providers()
    return providers


@router.get("/providers/{provider}/schema", response_model=ProviderSchema)
async def get_provider_schema(
    provider: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the schema for a provider's configuration."""
    config_manager = ProviderConfigManager(db)
    schema = await config_manager.get_provider_schema(provider)
    return ProviderSchema(fields=schema)


# Diff Engine Endpoints
@router.post("/diff", response_model=DiffResult)
async def compute_diff(
    original: str = Query(..., description="Original text"),
    modified: str = Query(..., description="Modified text"),
    token_type: str = Query("word", description="Token type: word, line, or character"),
):
    """Compute a diff between two texts."""
    from app.promptops.diff import DiffEngine
    
    diff_engine = DiffEngine(token_type=token_type)
    diff_result = diff_engine.diff(original, modified)
    return diff_result


@router.post("/diff/variables", response_model=Dict[str, Any])
async def compute_prompt_diff(
    original: str = Query(..., description="Original template"),
    modified: str = Query(..., description="Modified template"),
):
    """Compute a diff between two prompt templates with variable analysis."""
    diff_engine = PromptDiffEngine()
    diff_result = diff_engine.diff_with_variables(original, modified)
    return diff_result
