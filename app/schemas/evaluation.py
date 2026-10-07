import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvaluationCaseCreate(BaseModel):
    input_text: str = Field(..., min_length=1)
    expected_behavior: dict[str, Any] = Field(
        default_factory=dict,
        description="Reference notes shown to the judge (e.g. expected answer, constraints)",
    )


class EvaluationCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    ordinal: int
    input_text: str
    expected_behavior: dict[str, Any]
    created_at: datetime


class EvaluationDatasetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class EvaluationDatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    created_at: datetime
    case_count: int = 0


class EvaluationDatasetDetail(EvaluationDatasetResponse):
    cases: list[EvaluationCaseResponse] = []


class CriterionDef(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    weight: float = Field(1.0, gt=0)


class RubricCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    criteria: list[CriterionDef] = Field(..., min_length=1)
    scale_min: int = 1
    scale_max: int = 5


class RubricResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    version: int
    description: str | None = None
    scale_min: int
    scale_max: int
    criteria: list[dict[str, Any]]
    definition_hash: str


class RunSettings(BaseModel):
    """Optional per-run overrides; the values actually used are stored on the run."""

    case_concurrency: int | None = Field(None, ge=1, le=64)
    max_inflight_requests: int | None = Field(None, ge=1, le=128)
    requests_per_second: float | None = Field(None, ge=0)
    call_timeout_s: float | None = Field(None, gt=0, le=600)
    max_retries: int | None = Field(None, ge=0, le=8)
    judge_max_attempts: int | None = Field(None, ge=1, le=6)
    judge_position_strategy: str | None = Field(None, pattern="^(both|alternate|none)$")
    judge_include_prompts: bool | None = None


class EvaluationRunCreate(BaseModel):
    dataset_id: uuid.UUID
    prompt_version_a_id: uuid.UUID
    prompt_version_b_id: uuid.UUID
    provider: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    judge_provider: str | None = None
    judge_model: str | None = None
    rubric_id: uuid.UUID | None = None
    settings: RunSettings = Field(default_factory=RunSettings)


class RunProgress(BaseModel):
    total_cases: int
    completed_cases: int
    failed_cases: int


class EvaluationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    prompt_version_a_id: uuid.UUID
    prompt_version_b_id: uuid.UUID
    rubric_id: uuid.UUID
    provider: str
    model: str
    judge_provider: str
    judge_model: str
    config: dict[str, Any]
    status: str
    cancel_requested: bool
    attempts: int
    error: str | None = None
    total_cases: int
    created_by: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    version_a_label: str | None = None
    version_b_label: str | None = None
    dataset_name: str | None = None
    progress: RunProgress | None = None


class CandidateOutputResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slot: str
    prompt_version_id: uuid.UUID
    status: str
    error: str | None = None
    rendered_prompt: str
    output_text: str | None = None
    provider: str
    model: str
    generation_params: dict[str, Any]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    latency_ms: float
    attempts: int
    started_at: datetime
    completed_at: datetime


class RubricScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    criterion: str
    score_a: float
    score_b: float
    reason: str | None = None


class JudgeEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pass_index: int
    swapped: bool
    judge_provider: str
    judge_model: str
    rubric_version: int
    status: str
    error: str | None = None
    winner: str | None = None
    score_a: float | None = None
    score_b: float | None = None
    normalized_score_a: float | None = None
    normalized_score_b: float | None = None
    confidence: float | None = None
    reasoning: str | None = None
    raw_score: dict[str, Any] | None = None
    attempts: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: float
    latency_ms: float
    judged_at: datetime
    rubric_scores: list[RubricScoreResponse] = []


class CaseResultResponse(BaseModel):
    result_id: uuid.UUID
    case_id: uuid.UUID
    ordinal: int
    input_text: str
    expected_behavior: dict[str, Any]
    status: str
    error: str | None = None
    winner: str | None = None
    score_a: float | None = None
    score_b: float | None = None
    confidence: float | None = None
    position_consistent: bool | None = None
    outputs: list[CandidateOutputResponse] = []
    judge_evaluations: list[JudgeEvaluationResponse] = []


class SlotMetrics(BaseModel):
    outputs_completed: int
    outputs_failed: int
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    avg_score: float | None = None


class CriterionSummary(BaseModel):
    criterion: str
    avg_score_a: float
    avg_score_b: float
    samples: int


class RunSummary(BaseModel):
    run_id: uuid.UUID
    status: str
    total_cases: int
    completed_cases: int
    failed_cases: int
    wins_a: int
    wins_b: int
    ties: int
    win_rate_a: float | None = None
    win_rate_b: float | None = None
    tie_rate: float | None = None
    a_share_of_decisive: float | None = None
    a_share_ci_low: float | None = None
    a_share_ci_high: float | None = None
    avg_confidence: float | None = None
    position_consistency_rate: float | None = None
    rubric_scale_min: int
    rubric_scale_max: int
    slot_a: SlotMetrics
    slot_b: SlotMetrics
    criteria: list[CriterionSummary] = []
    judge_tokens: int = 0
    judge_cost: float = 0.0
    total_cost: float = 0.0
    note: str = ""
