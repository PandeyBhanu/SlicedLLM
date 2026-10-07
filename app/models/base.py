import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy 2.0 models."""

    # Automatically generate __tablename__ based on class name in lowercase
    @declared_attr.directive
    def __tablename__(cls) -> str:
        # Convert camelCase/PascalCase to snake_case table names
        name = cls.__name__
        import re

        return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower() + "s"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        sort_order=-10,  # Enforce id as the very first column
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        sort_order=10,  # Place timestamps toward the end
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        sort_order=11,
    )
