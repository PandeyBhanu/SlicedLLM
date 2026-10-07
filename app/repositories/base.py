import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Generic repository providing asynchronous base CRUD operations."""

    def __init__(self, model: type[ModelType], db: AsyncSession):
        self.model = model
        self.db = db

    async def get(self, id: uuid.UUID) -> ModelType | None:
        """Fetch a single record by its UUID."""
        query = select(self.model).where(self.model.id == id)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_multi(self, *, skip: int = 0, limit: int = 100) -> list[ModelType]:
        """Fetch multiple records with offset and limit."""
        query = select(self.model).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(self, *, obj_in: dict[str, Any]) -> ModelType:
        """Create a new record in the database."""
        db_obj = self.model(**obj_in)
        self.db.add(db_obj)
        await (
            self.db.flush()
        )  # Populates auto-generated fields (like id, timestamps) without committing transaction
        return db_obj

    async def update(self, *, db_obj: ModelType, obj_in: dict[str, Any] | Any) -> ModelType:
        """Update an existing record with dictionary or object data."""
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        for field in update_data:
            if hasattr(db_obj, field):
                setattr(db_obj, field, update_data[field])

        self.db.add(db_obj)
        await self.db.flush()
        return db_obj

    async def remove(self, *, id: uuid.UUID) -> ModelType | None:
        """Delete a record by its UUID."""
        obj = await self.get(id)
        if obj:
            await self.db.delete(obj)
            await self.db.flush()
        return obj
