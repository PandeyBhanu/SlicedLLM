import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class EvaluationDataset(Base):
    """A collection of test cases used to evaluate prompt behaviors."""
    
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    # Relationships
    cases: Mapped[List["EvaluationCase"]] = relationship(
        "EvaluationCase",
        back_populates="dataset",
        cascade="all, delete-orphan"
    )


class EvaluationCase(Base):
    """An individual test case comprising input data and expected response patterns."""
    
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_behavior: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False
    )

    # Relationships
    dataset: Mapped["EvaluationDataset"] = relationship("EvaluationDataset", back_populates="cases")
    results: Mapped[List["EvaluationResult"]] = relationship(
        "EvaluationResult",
        back_populates="case",
        cascade="all, delete-orphan"
    )


class EvaluationRun(Base):
    """Executes a comparative or standalone run across datasets."""
    
    prompt_version_a_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )
    prompt_version_b_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        index=True,
        nullable=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", index=True, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    prompt_version_a: Mapped["PromptVersion"] = relationship(
        "PromptVersion",
        foreign_keys=[prompt_version_a_id]
    )
    prompt_version_b: Mapped[Optional["PromptVersion"]] = relationship(
        "PromptVersion",
        foreign_keys=[prompt_version_b_id]
    )
    results: Mapped[List["EvaluationResult"]] = relationship(
        "EvaluationResult",
        back_populates="run",
        cascade="all, delete-orphan"
    )


class EvaluationResult(Base):
    """Detailed score, latencies, token usages, and costs of a test case execution."""
    
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )
    evaluation_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_cases.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )
    winner: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # "A", "B", "TIE", or None
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    token_usage: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False
    )
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Relationships
    run: Mapped["EvaluationRun"] = relationship("EvaluationRun", back_populates="results")
    case: Mapped["EvaluationCase"] = relationship("EvaluationCase", back_populates="results")
