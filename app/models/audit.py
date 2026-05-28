import uuid
from typing import Any, Dict, Optional
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """Stores full historical state changes and entity operations across the system."""
    
    entity_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(100), index=True, nullable=False)  # e.g., "CREATE", "UPDATE", "ROLLBACK", "ACTIVATE"
    
    before_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True
    )
    after_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True
    )
