import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, String, event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.exceptions import AppendOnlyError
from app.models.base import Base

GENESIS_HASH = "0" * 64


class AuditLog(Base):
    """Append-only, hash-chained record of a state change.

    `event_hash = sha256(canonical(event fields) + prev_hash)` and `prev_hash` is the previous
    event's `event_hash`, so editing/removing/reordering a row breaks the chain
    (see app/audit/service.py::verify_audit_chain). PostgreSQL triggers reject
    UPDATE/DELETE/TRUNCATE.
    """

    seq: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False, default="anonymous")
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


@event.listens_for(AuditLog, "before_update")
def _block_update(mapper, connection, target) -> None:
    raise AppendOnlyError("audit_logs is append-only: UPDATE is not allowed")


@event.listens_for(AuditLog, "before_delete")
def _block_delete(mapper, connection, target) -> None:
    raise AppendOnlyError("audit_logs is append-only: DELETE is not allowed")
