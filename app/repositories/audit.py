import uuid
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    """Repository handling custom queries for System Auditing."""

    def __init__(self, db: AsyncSession):
        super().__init__(AuditLog, db)

    async def get_by_entity(
        self, entity_type: str, entity_id: uuid.UUID
    ) -> List[AuditLog]:
        """Fetch audit log records associated with a specific entity."""
        query = (
            select(self.model)
            .where(
                self.model.entity_type == entity_type,
                self.model.entity_id == entity_id,
            )
            .order_by(self.model.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_action(self, action: str) -> List[AuditLog]:
        """Fetch audit logs filtered by a specific platform action."""
        query = (
            select(self.model)
            .where(self.model.action == action)
            .order_by(self.model.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
