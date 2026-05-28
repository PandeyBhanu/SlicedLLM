import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# Prompt Registry Schemas
class PromptCreate(BaseModel):
    """Schema for creating a new prompt."""
    name: str = Field(..., max_length=255, description="Unique name for the prompt")
    description: Optional[str] = Field(None, description="Description of the prompt")
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags for categorization")


class PromptUpdate(BaseModel):
    """Schema for updating prompt metadata."""
    name: Optional[str] = Field(None, max_length=255, description="New name for the prompt")
    description: Optional[str] = Field(None, description="New description")
    tags: Optional[List[str]] = Field(None, description="New tags")


class PromptTagsUpdate(BaseModel):
    """Schema for updating prompt tags."""
    tags: List[str] = Field(..., description="Tags to set")


class PromptTagsAdd(BaseModel):
    """Schema for adding tags to a prompt."""
    tags: List[str] = Field(..., description="Tags to add")


class PromptTagsRemove(BaseModel):
    """Schema for removing tags from a prompt."""
    tags: List[str] = Field(..., description="Tags to remove")


class PromptStatisticsResponse(BaseModel):
    """Schema for prompt statistics."""
    prompt_id: uuid.UUID
    name: str
    description: Optional[str]
    tags: List[str]
    total_versions: int
    active_version_id: Optional[uuid.UUID]
    active_version: Optional[str]
    latest_version_id: Optional[uuid.UUID]
    latest_version: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


# Version Management Schemas
class VersionCreate(BaseModel):
    """Schema for creating a new prompt version."""
    semantic_version: str = Field(..., description="Semantic version (e.g., '1.0.0')")
    template: str = Field(..., description="Prompt template content")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Version metadata")
    provider_config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Provider configuration")
    set_as_active: bool = Field(default=False, description="Whether to set as active version")


class VersionResponse(BaseModel):
    """Schema for prompt version response."""
    id: uuid.UUID
    prompt_id: uuid.UUID
    semantic_version: str
    template: str
    metadata: Dict[str, Any]
    provider_config: Dict[str, Any]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class VersionHistoryEntry(BaseModel):
    """Schema for version history entry."""
    version_id: str
    semantic_version: str
    is_active: bool
    created_at: Optional[str]
    template_length: int
    metadata: Dict[str, Any]
    provider_config: Dict[str, Any]


class VersionComparisonResponse(BaseModel):
    """Schema for version comparison."""
    version_a: Dict[str, Any]
    version_b: Dict[str, Any]
    version_comparison: str
    template_different: bool
    metadata_different: bool
    provider_config_different: bool


class NextVersionSuggestion(BaseModel):
    """Schema for next version suggestion."""
    current_version: str
    suggested_version: str
    change_type: str


# Activation and Rollback Schemas
class RollbackRequest(BaseModel):
    """Schema for rollback request."""
    version_id: Optional[uuid.UUID] = Field(None, description="Version ID to rollback to")
    semantic_version: Optional[str] = Field(None, description="Semantic version to rollback to")


class RollbackCandidate(BaseModel):
    """Schema for rollback candidate."""
    version_id: str
    semantic_version: str
    created_at: Optional[str]
    is_previous_active: bool


class ActivationHistoryEntry(BaseModel):
    """Schema for activation history entry."""
    version_id: str
    semantic_version: str
    activated_at: Optional[str]
    previous_version: Optional[str]


# Diff Engine Schemas
class DiffSegment(BaseModel):
    """Schema for diff segment."""
    change_type: str
    content: str
    position: int
    length: int


class DiffResult(BaseModel):
    """Schema for diff result."""
    original: str
    modified: str
    segments: List[DiffSegment]
    additions: int
    deletions: int
    unchanged: int
    similarity_ratio: float


class VariableDiffAnalysis(BaseModel):
    """Schema for variable diff analysis."""
    original: List[str]
    modified: List[str]
    added: List[str]
    removed: List[str]
    unchanged: List[str]


class PromptDiffResponse(BaseModel):
    """Schema for prompt diff response."""
    diff: DiffResult
    variables: VariableDiffAnalysis


# Changelog Schemas
class ChangelogEntry(BaseModel):
    """Schema for changelog entry."""
    version_id: str
    semantic_version: str
    timestamp: Optional[str]
    is_active: bool
    change_type: str
    description: str
    metadata: Dict[str, Any]
    provider_config: Dict[str, Any]
    diff: Optional[PromptDiffResponse] = None


class ChangeSummary(BaseModel):
    """Schema for change summary."""
    prompt_id: str
    prompt_name: str
    total_versions: int
    active_version: Optional[Dict[str, Any]]
    latest_version: Optional[Dict[str, Any]]
    total_changes: int
    first_version: Optional[str]
    last_updated: Optional[str]


# Audit Schemas
class AuditLogEntry(BaseModel):
    """Schema for audit log entry."""
    audit_log_id: str
    entity_type: str
    entity_id: str
    action: str
    timestamp: Optional[str]
    before_state: Optional[Dict[str, Any]]
    after_state: Optional[Dict[str, Any]]


# Provider Config Schemas
class ProviderConfigCreate(BaseModel):
    """Schema for creating provider config."""
    provider: str = Field(..., description="Provider name (e.g., 'ollama', 'groq')")
    config: Dict[str, Any] = Field(..., description="Provider configuration")


class ProviderConfigResponse(BaseModel):
    """Schema for provider config response."""
    provider: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None


class ProviderSchemaField(BaseModel):
    """Schema for provider schema field."""
    type: str
    min: Optional[float] = None
    max: Optional[float] = None
    default: Optional[Any] = None
    description: str


class ProviderSchema(BaseModel):
    """Schema for provider configuration schema."""
    fields: Dict[str, ProviderSchemaField]


# Semantic Versioning Schemas
class SemanticVersionResponse(BaseModel):
    """Schema for semantic version response."""
    major: int
    minor: int
    patch: int
    version_string: str


class VersionValidationResponse(BaseModel):
    """Schema for version validation response."""
    is_valid: bool
    error_message: Optional[str] = None


# Combined Response Schemas
class PromptWithVersionsResponse(BaseModel):
    """Schema for prompt with versions."""
    id: uuid.UUID
    name: str
    description: Optional[str]
    tags: List[str]
    created_at: datetime
    updated_at: datetime
    versions: List[VersionResponse] = []

    class Config:
        from_attributes = True


class FullPromptResponse(BaseModel):
    """Schema for full prompt response with all details."""
    prompt: PromptWithVersionsResponse
    statistics: PromptStatisticsResponse
    changelog: List[ChangelogEntry] = []
