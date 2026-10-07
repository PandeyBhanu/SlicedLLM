"""Append-only, hash-chained audit trail.

Design
------
* Every event gets a global, gap-free `seq` and stores `prev_hash` (the previous event's hash).
* `event_hash = sha256(canonical_json(event fields incl. seq and prev_hash))`.
* Appends are serialized with a transaction-scoped PostgreSQL advisory lock so two concurrent
  transactions can never both extend the same head. The event is written in the SAME transaction
  as the state change it describes: either both commit or neither does.
* PostgreSQL triggers reject UPDATE/DELETE/TRUNCATE (app/db/ddl.py). A superuser can still bypass
  triggers, but cannot do so undetectably: `verify_audit_chain` recomputes the chain.

Known limit: deleting the newest N events leaves a valid (shorter) chain. Detecting that needs an
externally stored head checkpoint - pass it as `expected_head` to `verify_audit_chain`.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import AuditContext
from app.models.audit import GENESIS_HASH, AuditLog
from app.promptops.hashing import canonical_json, sha256_hex

logger = structlog.get_logger(__name__)

AUDIT_LOCK_KEY = 0x5C1CED11  # arbitrary constant: "sliced-llm audit head"


def compute_event_hash(event: dict[str, Any]) -> str:
    """Hash of the event body. `event` must hold exactly the fields listed below."""
    body = {
        "seq": event["seq"],
        "id": str(event["id"]),
        "occurred_at": event["occurred_at"].astimezone(UTC).isoformat(),
        "actor_id": event["actor_id"],
        "request_id": event["request_id"],
        "entity_type": event["entity_type"],
        "entity_id": str(event["entity_id"]),
        "action": event["action"],
        "before_state": event["before_state"],
        "after_state": event["after_state"],
        "content_hash": event["content_hash"],
        "prev_hash": event["prev_hash"],
    }
    return sha256_hex(canonical_json(body))


def _event_dict(row: AuditLog) -> dict[str, Any]:
    return {
        "seq": row.seq,
        "id": row.id,
        "occurred_at": row.occurred_at,
        "actor_id": row.actor_id,
        "request_id": row.request_id,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "action": row.action,
        "before_state": row.before_state,
        "after_state": row.after_state,
        "content_hash": row.content_hash,
        "prev_hash": row.prev_hash,
    }


class AuditService:
    """Write side of the audit trail. There is deliberately no update/delete method."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def append(
        self,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        ctx: AuditContext,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        content_hash: str | None = None,
    ) -> AuditLog:
        # Held until the surrounding transaction ends, so the chain head cannot fork.
        await self.db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": AUDIT_LOCK_KEY})
        head = (
            await self.db.execute(
                select(AuditLog.seq, AuditLog.event_hash).order_by(AuditLog.seq.desc()).limit(1)
            )
        ).first()
        event = {
            "seq": (head.seq + 1) if head else 1,
            "id": uuid.uuid4(),
            "occurred_at": datetime.now(UTC),
            "actor_id": ctx.actor_id,
            "request_id": ctx.request_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "before_state": before_state,
            "after_state": after_state,
            "content_hash": content_hash,
            "prev_hash": head.event_hash if head else GENESIS_HASH,
        }
        event["event_hash"] = compute_event_hash(event)
        row = AuditLog(**event)
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_events(
        self,
        *,
        entity_type: str | None = None,
        entity_ids: list[uuid.UUID] | None = None,
        limit: int = 100,
    ) -> list[AuditLog]:
        query = select(AuditLog).order_by(AuditLog.seq.desc()).limit(limit)
        if entity_type:
            query = query.where(AuditLog.entity_type == entity_type)
        if entity_ids is not None:
            query = query.where(AuditLog.entity_id.in_(entity_ids))
        return list((await self.db.execute(query)).scalars().all())

    async def head(self) -> tuple[int, str] | None:
        row = (
            await self.db.execute(
                select(AuditLog.seq, AuditLog.event_hash).order_by(AuditLog.seq.desc()).limit(1)
            )
        ).first()
        return (row.seq, row.event_hash) if row else None

    async def count(self) -> int:
        return (await self.db.execute(select(func.count()).select_from(AuditLog))).scalar_one()


@dataclass
class AuditVerification:
    valid: bool
    events_checked: int
    head_seq: int | None
    head_hash: str | None
    errors: list[dict[str, Any]] = field(default_factory=list)


async def verify_audit_chain(
    db: AsyncSession, *, expected_head: tuple[int, str] | None = None
) -> AuditVerification:
    """Recompute the whole chain and report every inconsistency.

    Detects: modified events (hash mismatch), deleted events (seq gap / prev_hash break),
    reordered or back-dated events (seq vs occurred_at), and - if `expected_head` is supplied -
    truncation of the tail.
    """
    rows = (await db.execute(select(AuditLog).order_by(AuditLog.seq.asc()))).scalars().all()
    errors: list[dict[str, Any]] = []
    prev_hash = GENESIS_HASH
    prev_seq = 0
    prev_time: datetime | None = None

    for row in rows:
        if row.seq != prev_seq + 1:
            errors.append(
                {"seq": row.seq, "kind": "missing_events", "detail": f"expected seq {prev_seq + 1}"}
            )
        if row.prev_hash != prev_hash:
            errors.append(
                {
                    "seq": row.seq,
                    "kind": "broken_chain",
                    "detail": "prev_hash does not match previous event",
                }
            )
        if compute_event_hash(_event_dict(row)) != row.event_hash:
            errors.append(
                {
                    "seq": row.seq,
                    "kind": "modified_event",
                    "detail": "event_hash does not match contents",
                }
            )
        if prev_time is not None and row.occurred_at < prev_time:
            errors.append(
                {
                    "seq": row.seq,
                    "kind": "out_of_order",
                    "detail": "occurred_at earlier than previous event",
                }
            )
        prev_hash, prev_seq, prev_time = row.event_hash, row.seq, row.occurred_at

    head = (rows[-1].seq, rows[-1].event_hash) if rows else None
    if expected_head is not None and head != tuple(expected_head):
        errors.append(
            {
                "seq": head[0] if head else 0,
                "kind": "head_mismatch",
                "detail": "head differs from checkpoint",
            }
        )

    return AuditVerification(
        valid=not errors,
        events_checked=len(rows),
        head_seq=head[0] if head else None,
        head_hash=head[1] if head else None,
        errors=errors,
    )
