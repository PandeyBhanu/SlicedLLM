from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.audit import AuditService, verify_audit_chain
from app.schemas.audit import AuditLogResponse, AuditVerificationResponse

router = APIRouter()


@router.get("/events", response_model=list[AuditLogResponse])
async def list_audit_events(
    entity_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    return await AuditService(db).list_events(entity_type=entity_type, limit=limit)


@router.get("/verify", response_model=AuditVerificationResponse)
async def verify_chain(db: AsyncSession = Depends(get_db)):
    """Recompute the hash chain and report modified/deleted/reordered events."""
    result = await verify_audit_chain(db)
    return AuditVerificationResponse(
        valid=result.valid,
        events_checked=result.events_checked,
        head_seq=result.head_seq,
        head_hash=result.head_hash,
        errors=result.errors,
    )
