import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

RUN_STATUSES = ("PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED")
TERMINAL_RUN_STATUSES = ("COMPLETED", "FAILED", "CANCELLED")


class EvaluationDataset(Base):
    """A named collection of test cases."""

    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    cases: Mapped[list["EvaluationCase"]] = relationship(
        "EvaluationCase",
        back_populates="dataset",
        order_by="EvaluationCase.ordinal",
        lazy="raise",
    )


class EvaluationCase(Base):
    """One test input plus what a good answer looks like (free-form JSON shown to the judge)."""

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_behavior: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )

    dataset: Mapped["EvaluationDataset"] = relationship(
        "EvaluationDataset", back_populates="cases", lazy="raise"
    )

    __table_args__ = (UniqueConstraint("dataset_id", "ordinal", name="uq_case_dataset_ordinal"),)


class Rubric(Base):
    """Versioned, explicit judging criteria. (name, version) is immutable by convention + hash."""

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scale_min: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    scale_max: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # [{"name": "correctness", "description": "...", "weight": 1.0}, ...]
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (UniqueConstraint("name", "version", name="uq_rubric_name_version"),)


class EvaluationRun(Base):
    """An A/B evaluation job. Doubles as the durable job record (status + heartbeat)."""

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_datasets.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    prompt_version_a_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    prompt_version_b_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    rubric_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rubrics.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    judge_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    judge_model: Mapped[str] = mapped_column(String(100), nullable=False)
    # Everything that influenced execution (concurrency, timeouts, retries, judge strategy, ...).
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )

    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="anonymous", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    dataset: Mapped["EvaluationDataset"] = relationship("EvaluationDataset", lazy="raise")
    rubric: Mapped["Rubric"] = relationship("Rubric", lazy="raise")

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_run_status",
        ),
        Index("ix_runs_status_created", "status", "created_at"),
    )


class EvaluationResult(Base):
    """Final, normalized comparison for one (run, case). Judge detail lives in JudgeEvaluation."""

    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    evaluation_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # COMPLETED | FAILED
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    winner: Mapped[str | None] = mapped_column(String(10), nullable=True)  # A | B | TIE
    # Mean over judge passes of the rubric-weighted score, on the rubric scale (e.g. 1..5).
    score_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_consistent: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    outputs: Mapped[list["CandidateOutput"]] = relationship(
        "CandidateOutput", back_populates="result", lazy="raise"
    )
    judge_evaluations: Mapped[list["JudgeEvaluation"]] = relationship(
        "JudgeEvaluation",
        back_populates="result",
        order_by="JudgeEvaluation.pass_index",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("evaluation_run_id", "evaluation_case_id", name="uq_result_run_case"),
        CheckConstraint("status IN ('COMPLETED','FAILED')", name="ck_result_status"),
        CheckConstraint("winner IS NULL OR winner IN ('A','B','TIE')", name="ck_result_winner"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_result_conf"
        ),
    )


class CandidateOutput(Base):
    """The exact output one prompt version produced for one case in one run."""

    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    evaluation_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False
    )
    result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evaluation_results.id", ondelete="CASCADE"), index=True, nullable=True
    )
    slot: Mapped[str] = mapped_column(String(1), nullable=False)  # 'A' | 'B'
    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # COMPLETED | FAILED
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    generation_params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    result: Mapped[Optional["EvaluationResult"]] = relationship(
        "EvaluationResult", back_populates="outputs", lazy="raise"
    )

    __table_args__ = (
        UniqueConstraint(
            "evaluation_run_id", "evaluation_case_id", "slot", name="uq_output_run_case_slot"
        ),
        CheckConstraint("slot IN ('A','B')", name="ck_output_slot"),
        CheckConstraint("status IN ('COMPLETED','FAILED')", name="ck_output_status"),
        Index("ix_output_case", "evaluation_case_id"),
    )


class JudgeEvaluation(Base):
    """One judge call (one position ordering) on a pair of outputs."""

    result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_results.id", ondelete="CASCADE"), nullable=False
    )
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    pass_index: Mapped[int] = mapped_column(Integer, nullable=False)
    swapped: Mapped[bool] = mapped_column(Boolean, nullable=False)
    judge_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    judge_model: Mapped[str] = mapped_column(String(100), nullable=False)
    rubric_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rubrics.id"), nullable=False)
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # COMPLETED | FAILED
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Validated judge JSON exactly as returned (positions as the judge saw them).
    raw_score: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Normalized back to candidate terms (A = version A's output) on the rubric scale.
    winner: Mapped[str | None] = mapped_column(String(10), nullable=True)
    score_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_score_a: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1
    normalized_score_b: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    judged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    result: Mapped["EvaluationResult"] = relationship(
        "EvaluationResult", back_populates="judge_evaluations", lazy="raise"
    )
    rubric_scores: Mapped[list["RubricScore"]] = relationship(
        "RubricScore", back_populates="judge_evaluation", lazy="raise"
    )

    __table_args__ = (
        UniqueConstraint("result_id", "pass_index", name="uq_judge_result_pass"),
        CheckConstraint("status IN ('COMPLETED','FAILED')", name="ck_judge_status"),
        CheckConstraint("winner IS NULL OR winner IN ('A','B','TIE')", name="ck_judge_winner"),
    )


class RubricScore(Base):
    """Per-criterion scores of one judge call, normalized to candidate A / candidate B."""

    judge_evaluation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("judge_evaluations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    criterion: Mapped[str] = mapped_column(String(100), nullable=False)
    score_a: Mapped[float] = mapped_column(Float, nullable=False)
    score_b: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    judge_evaluation: Mapped["JudgeEvaluation"] = relationship(
        "JudgeEvaluation", back_populates="rubric_scores", lazy="raise"
    )

    __table_args__ = (
        UniqueConstraint("judge_evaluation_id", "criterion", name="uq_rubricscore_judge_criterion"),
    )
