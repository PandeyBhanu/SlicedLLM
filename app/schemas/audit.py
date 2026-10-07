import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seq: int
    occurred_at: datetime
    actor_id: str
    request_id: str | None = None
    entity_type: str
    entity_id: uuid.UUID
    action: str
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    content_hash: str | None = None
    prev_hash: str
    event_hash: str


class AuditVerificationResponse(BaseModel):
    valid: bool
    events_checked: int
    head_seq: int | None = None
    head_hash: str | None = None
    errors: list[dict[str, Any]] = []
