import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ImmutableEntityError
from app.models.prompt import Prompt, PromptVersion
from app.repositories.base import BaseRepository


class PromptRepository(BaseRepository[Prompt]):
    def __init__(self, db: AsyncSession):
        super().__init__(Prompt, db)

    async def get_by_name(self, name: str) -> Prompt | None:
        result = await self.db.execute(select(Prompt).where(Prompt.name == name))
        return result.scalars().first()

    async def get_for_update(self, prompt_id: uuid.UUID) -> Prompt | None:
        """Row-lock the prompt: serializes version creation / activation per prompt."""
        result = await self.db.execute(
            select(Prompt).where(Prompt.id == prompt_id).with_for_update()
        )
        return result.scalars().first()

    async def list_with_stats(self, *, skip: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Prompts plus version_count / active / latest version, in two queries."""
        prompts = (
            (
                await self.db.execute(
                    select(Prompt).order_by(Prompt.created_at.desc()).offset(skip).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        if not prompts:
            return []
        ids = [p.id for p in prompts]
        versions = (
            (
                await self.db.execute(
                    select(PromptVersion)
                    .where(PromptVersion.prompt_id.in_(ids))
                    .order_by(PromptVersion.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        by_prompt: dict[uuid.UUID, list[PromptVersion]] = {}
        for v in versions:
            by_prompt.setdefault(v.prompt_id, []).append(v)
        out = []
        for p in prompts:
            vs = by_prompt.get(p.id, [])
            active = next((v for v in vs if v.is_active), None)
            out.append(
                {
                    "prompt": p,
                    "version_count": len(vs),
                    "active_version": active.semantic_version if active else None,
                    "active_version_id": active.id if active else None,
                    "latest_version": vs[-1].semantic_version if vs else None,
                }
            )
        return out

    async def count(self) -> int:
        return (await self.db.execute(select(func.count()).select_from(Prompt))).scalar_one()


class PromptVersionRepository(BaseRepository[PromptVersion]):
    """Only `set_active` may mutate a stored version; generic update/remove are disabled."""

    def __init__(self, db: AsyncSession):
        super().__init__(PromptVersion, db)

    async def update(self, *args: Any, **kwargs: Any) -> PromptVersion:  # type: ignore[override]
        raise ImmutableEntityError("Prompt versions are immutable; create a new version instead")

    async def remove(self, *args: Any, **kwargs: Any) -> PromptVersion | None:  # type: ignore[override]
        raise ImmutableEntityError("Prompt versions cannot be deleted")

    async def get_by_version(
        self, prompt_id: uuid.UUID, semantic_version: str
    ) -> PromptVersion | None:
        result = await self.db.execute(
            select(PromptVersion).where(
                PromptVersion.prompt_id == prompt_id,
                PromptVersion.semantic_version == semantic_version,
            )
        )
        return result.scalars().first()

    async def get_active_version(self, prompt_id: uuid.UUID) -> PromptVersion | None:
        result = await self.db.execute(
            select(PromptVersion).where(
                PromptVersion.prompt_id == prompt_id, PromptVersion.is_active.is_(True)
            )
        )
        return result.scalars().first()

    async def get_versions_by_prompt(self, prompt_id: uuid.UUID) -> list[PromptVersion]:
        result = await self.db.execute(
            select(PromptVersion)
            .where(PromptVersion.prompt_id == prompt_id)
            .order_by(PromptVersion.created_at.asc(), PromptVersion.semantic_version.asc())
        )
        return list(result.scalars().all())

    async def set_active(self, prompt_id: uuid.UUID, version_id: uuid.UUID | None) -> None:
        """Deactivate the prompt's active version and (optionally) activate `version_id`.

        Two separate statements: the partial unique index is checked per statement, so the old
        row must be cleared first. Content columns are never touched.
        """
        await self.db.execute(
            update(PromptVersion)
            .where(PromptVersion.prompt_id == prompt_id, PromptVersion.is_active.is_(True))
            .values(is_active=False)
        )
        if version_id is not None:
            await self.db.execute(
                update(PromptVersion).where(PromptVersion.id == version_id).values(is_active=True)
            )
        await self.db.flush()
