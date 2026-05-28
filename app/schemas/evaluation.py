import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# Evaluation Case schemas
class EvaluationCaseCreate(BaseModel):
    input_text: str = Field(..., description="The query, instructions, or inputs fed to the prompt template")
    expected_behavior: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured verification patterns (keywords, length, schema criteria, LLM-as-a-judge expectations)"
    )


class EvaluationCaseResponse(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    input_text: str
    expected_behavior: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


# Evaluation Dataset schemas
class EvaluationDatasetCreate(BaseModel):
    name: str = Field(..., max_length=255, description="Unique name for the testing/evaluation dataset")
    description: Optional[str] = Field(None, description="Scope and purpose of this dataset")


class EvaluationDatasetResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    created_at: datetime
    cases: List[EvaluationCaseResponse] = []

    class Config:
        from_attributes = True


# Evaluation Result schemas
class EvaluationResultResponse(BaseModel):
    id: uuid.UUID
    evaluation_run_id: uuid.UUID
    evaluation_case_id: uuid.UUID
    winner: Optional[str] = None  # "A", "B", "TIE", or None (if single evaluation)
    confidence_score: float
    reasoning: Optional[str] = None
    latency_ms: float
    token_usage: Dict[str, Any]
    estimated_cost: float
    created_at: datetime

    class Config:
        from_attributes = True


# Evaluation Run schemas
class EvaluationRunCreate(BaseModel):
    dataset_id: uuid.UUID = Field(..., description="The evaluation dataset to run test cases from")
    prompt_version_a_id: uuid.UUID = Field(..., description="Target candidate prompt version ID")
    prompt_version_b_id: Optional[uuid.UUID] = Field(
        None,
        description="Optional comparative baseline prompt version ID"
    )
    provider: str = Field(..., description="LLM provider, e.g. 'openai'")
    model: str = Field(..., description="Target model name, e.g. 'gpt-4o'")


class EvaluationRunResponse(BaseModel):
    id: uuid.UUID
    prompt_version_a_id: uuid.UUID
    prompt_version_b_id: Optional[uuid.UUID] = None
    provider: str
    model: str
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    results: List[EvaluationResultResponse] = []

    class Config:
        from_attributes = True


# Evaluation Report schemas
class RubricSummarySchema(BaseModel):
    rubric_name: str
    total_evaluations: int
    passed_count: int
    failed_count: int
    pass_rate: float
    average_confidence: float
    common_failures: List[str] = []


class LatencyMetricsSchema(BaseModel):
    average_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float


class CostMetricsSchema(BaseModel):
    total_cost: float
    average_cost_per_evaluation: float
    total_tokens: int
    average_tokens_per_evaluation: float


class VersionPerformanceSchema(BaseModel):
    version_id: str
    version_label: str
    overall_score: float
    pass_rate: float
    latency_metrics: LatencyMetricsSchema
    cost_metrics: CostMetricsSchema
    rubric_summaries: List[RubricSummarySchema] = []


class ComparisonReportSchema(BaseModel):
    report_id: str
    generated_at: datetime
    evaluation_run_id: str
    version_a: VersionPerformanceSchema
    version_b: Optional[VersionPerformanceSchema] = None
    comparison_summary: Dict[str, Any] = {}
    recommendations: List[str] = []
    detailed_findings: List[str] = []


class EvaluationHistoryResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    provider: str
    model: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    total_cases: int
    successful_cases: int
    passed_cases: int
    average_latency_ms: float
    total_cost: float
