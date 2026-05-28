import uuid
from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt import Prompt, PromptVersion
from app.repositories.base import BaseRepository


class PromptRepository(BaseRepository[Prompt]):
    """Repository handling custom queries for Prompts."""

    def __init__(self, db: AsyncSession):
        super().__init__(Prompt, db)

    async def get_by_name(self, name: str) -> Optional[Prompt]:
        """Fetch a prompt by its unique name."""
        query = select(self.model).where(self.model.name == name)
        result = await self.db.execute(query)
        return result.scalars().first()


class PromptVersionRepository(BaseRepository[PromptVersion]):
    """Repository handling custom queries for Prompt Versions."""

    def __init__(self, db: AsyncSession):
        super().__init__(PromptVersion, db)

    async def get_by_version(
        self, prompt_id: uuid.UUID, semantic_version: str
    ) -> Optional[PromptVersion]:
        """Retrieve a specific version of a prompt by semantic version."""
        query = select(self.model).where(
            self.model.prompt_id == prompt_id,
            self.model.semantic_version == semantic_version,
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_active_version(self, prompt_id: uuid.UUID) -> Optional[PromptVersion]:
        """Fetch the currently active/released prompt version."""
        query = select(self.model).where(
            self.model.prompt_id == prompt_id,
            self.model.is_active == True,  # noqa
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def deactivate_all_versions(self, prompt_id: uuid.UUID) -> None:
        """Deactivate all versions for a given prompt (usually before activating a new one)."""
        query = (
            update(self.model)
            .where(self.model.prompt_id == prompt_id, self.model.is_active == True)  # noqa
            .values(is_active=False)
        )
        await self.db.execute(query)
        await self.db.flush()

    async def get_versions_by_prompt(self, prompt_id: uuid.UUID) -> List[PromptVersion]:
        """Fetch all versions of a given prompt, ordered by creation date descending."""
        query = (
            select(self.model)
            .where(self.model.prompt_id == prompt_id)
            .order_by(self.model.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
