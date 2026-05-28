import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PromptBase(BaseModel):
    name: str = Field(..., max_length=255, description="The unique identity name of the prompt")
    description: Optional[str] = Field(None, description="A clear explanation of what this prompt targets")


class PromptCreate(PromptBase):
    pass


class PromptUpdate(BaseModel):
    description: Optional[str] = Field(None, description="Modify the description of the prompt container")


# Prompt Version schemas
class PromptVersionCreate(BaseModel):
    template: str = Field(..., description="The Jinja-like text template with placeholders, e.g. 'Hello {{name}}'")
    semantic_version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$", description="Semantic version string, e.g. '1.0.0'")
    metadata_json: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata for organizing/tagging versions")
    provider_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="LLM invocation configs like temperature, max_tokens, frequency_penalty, etc."
    )


class PromptVersionResponse(BaseModel):
    id: uuid.UUID
    prompt_id: uuid.UUID
    semantic_version: str
    template: str
    metadata_json: Dict[str, Any]
    provider_config: Dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PromptResponse(PromptBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    versions: List[PromptVersionResponse] = []

    class Config:
        from_attributes = True


# Specialized payload and response models
class PromptRollbackRequest(BaseModel):
    target_version_id: uuid.UUID = Field(..., description="The version ID to restore as the active model")


class PromptDiffResponse(BaseModel):
    prompt_id: uuid.UUID
    version_a: str
    version_b: str
    template_diff: str = Field(..., description="Unified line diff of prompt templates")
    config_diff: Dict[str, Any] = Field(..., description="Differences between JSON configuration objects")
