import uuid
from typing import Any, Dict, List
from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Prompt(Base):
    """Represents a named AI prompt template grouping."""
    
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    tags: Mapped[List[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False
    )

    # Relationships
    versions: Mapped[List["PromptVersion"]] = relationship(
        "PromptVersion",
        back_populates="prompt",
        cascade="all, delete-orphan",
        order_by="desc(PromptVersion.created_at)"
    )


class PromptVersion(Base):
    """An immutable version of a prompt template."""
    
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompts.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )
    semantic_version: Mapped[str] = mapped_column(String(50), nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False
    )
    provider_config: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)

    # Relationships
    prompt: Mapped["Prompt"] = relationship("Prompt", back_populates="versions")

    # Composite Unique constraint to prevent duplicate versions under the same prompt
    __table_args__ = (
        UniqueConstraint("prompt_id", "semantic_version", name="uq_prompt_id_semantic_version"),
        # Partial index: only one active version per prompt is allowed
        Index(
            "ix_only_one_active_version_per_prompt",
            "prompt_id",
            unique=True,
            postgresql_where=is_active == True,
        ),
    )
