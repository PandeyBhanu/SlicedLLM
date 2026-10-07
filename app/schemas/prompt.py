import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PromptCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)


class PromptUpdate(BaseModel):
    description: str | None = None
    tags: list[str] | None = None


class PromptVersionCreate(BaseModel):
    template: str = Field(
        ..., min_length=1, description="Template text; use {{input}} for the test input"
    )
    semantic_version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$", examples=["1.0.0"])
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    provider_config: dict[str, Any] = Field(
        default_factory=dict, description="temperature, max_tokens, top_p, ..."
    )
    set_as_active: bool = False


class PromptVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    prompt_id: uuid.UUID
    semantic_version: str
    template: str
    metadata_json: dict[str, Any]
    provider_config: dict[str, Any]
    content_hash: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PromptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime


class PromptSummaryResponse(PromptResponse):
    version_count: int = 0
    active_version: str | None = None
    active_version_id: uuid.UUID | None = None
    latest_version: str | None = None


class PromptDetailResponse(PromptResponse):
    versions: list[PromptVersionResponse] = []


class PromptRollbackRequest(BaseModel):
    target_version_id: uuid.UUID


class VersionIntegrityResponse(BaseModel):
    version_id: uuid.UUID
    stored_hash: str
    computed_hash: str
    intact: bool


class DiffSegmentSchema(BaseModel):
    op: str
    text: str
    token_count: int


class DiffStatsSchema(BaseModel):
    added: int
    removed: int
    unchanged: int
    similarity: float


class TokenDiffSchema(BaseModel):
    granularity: str
    tokenizer: str
    approximate_tokenizer: bool
    algorithm: str
    coarse: bool
    original_units: int
    modified_units: int
    original_tokens: int
    modified_tokens: int
    stats: DiffStatsSchema
    segments: list[DiffSegmentSchema]


class VariableDiffSchema(BaseModel):
    added: list[str]
    removed: list[str]
    unchanged: list[str]


class PromptDiffResponse(BaseModel):
    prompt_id: uuid.UUID
    version_a: PromptVersionResponse
    version_b: PromptVersionResponse
    template_diff: TokenDiffSchema
    variables: VariableDiffSchema
    config_diff: dict[str, Any]
    metadata_diff: dict[str, Any]


class ChangelogEntry(BaseModel):
    version_id: uuid.UUID
    semantic_version: str
    content_hash: str
    is_active: bool
    created_at: datetime
    previous_version: str | None = None
    diff_stats: DiffStatsSchema | None = None
    tokenizer: str | None = None
