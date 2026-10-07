import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, attributes, mapped_column, relationship

from app.core.exceptions import ImmutableEntityError
from app.models.base import Base

# Columns that define a version's identity/content. They are frozen at insert time.
IMMUTABLE_VERSION_FIELDS = (
    "prompt_id",
    "semantic_version",
    "template",
    "metadata_json",
    "provider_config",
    "content_hash",
)


class Prompt(Base):
    """A named prompt. Content lives in immutable PromptVersion rows."""

    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )

    versions: Mapped[list["PromptVersion"]] = relationship(
        "PromptVersion",
        back_populates="prompt",
        order_by="PromptVersion.created_at",
        lazy="raise",
    )


class PromptVersion(Base):
    """An immutable version of a prompt template.

    Only `is_active` (and bookkeeping `updated_at`) may change after insert. This is enforced
    three times: by the ORM guard below, by `PromptVersionRepository`, and by a PostgreSQL
    trigger (see app/db/ddl.py). `content_hash` lets anyone detect out-of-band tampering.
    """

    prompt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompts.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    semantic_version: Mapped[str] = mapped_column(String(50), nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    provider_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)

    prompt: Mapped["Prompt"] = relationship("Prompt", back_populates="versions", lazy="raise")

    __table_args__ = (
        UniqueConstraint("prompt_id", "semantic_version", name="uq_prompt_id_semantic_version"),
        # Partial unique index: at most one active version per prompt.
        Index(
            "ix_only_one_active_version_per_prompt",
            "prompt_id",
            unique=True,
            postgresql_where=(is_active == True),  # noqa: E712
        ),
    )


@event.listens_for(PromptVersion, "before_update")
def _guard_version_update(mapper, connection, target: PromptVersion) -> None:
    for field in IMMUTABLE_VERSION_FIELDS:
        if attributes.get_history(target, field).has_changes():
            raise ImmutableEntityError(f"PromptVersion.{field} is immutable")


@event.listens_for(PromptVersion, "before_delete")
def _guard_version_delete(mapper, connection, target: PromptVersion) -> None:
    raise ImmutableEntityError("PromptVersion rows cannot be deleted")
