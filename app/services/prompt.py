import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditService
from app.core.context import AuditContext
from app.core.exceptions import ConcurrencyError, EntityNotFoundException, ValidationError
from app.diff import diff_texts
from app.models.audit import AuditLog
from app.models.prompt import Prompt, PromptVersion
from app.promptops.hashing import compute_content_hash
from app.promptops.templates import extract_variables
from app.promptops.versioning import SemanticVersion
from app.repositories.prompt import PromptRepository, PromptVersionRepository
from app.schemas.prompt import PromptCreate, PromptUpdate, PromptVersionCreate

logger = structlog.get_logger(__name__)


def _prompt_state(p: Prompt) -> dict[str, Any]:
    return {"name": p.name, "description": p.description, "tags": list(p.tags or [])}


def _version_state(v: PromptVersion) -> dict[str, Any]:
    return {
        "version_id": str(v.id),
        "prompt_id": str(v.prompt_id),
        "semantic_version": v.semantic_version,
        "template": v.template,
        "metadata": v.metadata_json,
        "provider_config": v.provider_config,
        "content_hash": v.content_hash,
        "is_active": v.is_active,
    }


class PromptService:
    """The single place where prompts and prompt versions are mutated.

    Every mutation writes its audit event in the same transaction (app/audit/service.py).
    Mutations on one prompt are serialized by a row lock on the `prompts` row.
    """

    def __init__(self, db: AsyncSession, ctx: AuditContext | None = None):
        self.db = db
        self.ctx = ctx or AuditContext()
        self.prompts = PromptRepository(db)
        self.versions = PromptVersionRepository(db)
        self.audit = AuditService(db)

    # ---- prompts -----------------------------------------------------------------------------
    async def create_prompt(self, schema: PromptCreate) -> Prompt:
        if await self.prompts.get_by_name(schema.name):
            raise ValidationError(f"Prompt '{schema.name}' already exists.", {"name": schema.name})
        try:
            prompt = await self.prompts.create(obj_in=schema.model_dump())
            await self.audit.append(
                entity_type="Prompt",
                entity_id=prompt.id,
                action="CREATE",
                ctx=self.ctx,
                after_state=_prompt_state(prompt),
            )
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConcurrencyError(f"Prompt '{schema.name}' already exists.") from exc
        return prompt

    async def update_prompt(self, prompt_id: uuid.UUID, schema: PromptUpdate) -> Prompt:
        prompt = await self.prompts.get_for_update(prompt_id)
        if not prompt:
            raise EntityNotFoundException(f"Prompt '{prompt_id}' was not found.")
        before = _prompt_state(prompt)
        changes = schema.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(prompt, key, value)
        await self.db.flush()
        await self.db.refresh(prompt)
        await self.audit.append(
            entity_type="Prompt",
            entity_id=prompt.id,
            action="UPDATE",
            ctx=self.ctx,
            before_state=before,
            after_state=_prompt_state(prompt),
        )
        await self.db.commit()
        return prompt

    async def get_prompt(self, prompt_id: uuid.UUID) -> Prompt:
        prompt = await self.prompts.get(prompt_id)
        if not prompt:
            raise EntityNotFoundException(f"Prompt '{prompt_id}' was not found.")
        return prompt

    async def get_prompt_with_versions(self, prompt_id: uuid.UUID) -> dict[str, Any]:
        prompt = await self.get_prompt(prompt_id)
        versions = await self.versions.get_versions_by_prompt(prompt_id)
        return {"prompt": prompt, "versions": versions}

    async def list_prompts(self, skip: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        return await self.prompts.list_with_stats(skip=skip, limit=limit)

    # ---- versions ----------------------------------------------------------------------------
    async def create_prompt_version(
        self, prompt_id: uuid.UUID, schema: PromptVersionCreate
    ) -> PromptVersion:
        prompt = await self.prompts.get_for_update(prompt_id)  # serialize concurrent creators
        if not prompt:
            raise EntityNotFoundException(f"Prompt '{prompt_id}' was not found.")
        if await self.versions.get_by_version(prompt_id, schema.semantic_version):
            raise ValidationError(
                f"Version '{schema.semantic_version}' already exists for this prompt.",
                {"prompt_id": str(prompt_id), "semantic_version": schema.semantic_version},
            )

        previous = await self.versions.get_active_version(prompt_id)
        make_active = schema.set_as_active or previous is None
        content_hash = compute_content_hash(
            prompt_id=prompt_id,
            semantic_version=schema.semantic_version,
            template=schema.template,
            metadata=schema.metadata_json,
            provider_config=schema.provider_config,
        )
        try:
            if make_active:
                await self.versions.set_active(prompt_id, None)
            version = await self.versions.create(
                obj_in={
                    "prompt_id": prompt_id,
                    "semantic_version": schema.semantic_version,
                    "template": schema.template,
                    "metadata_json": schema.metadata_json,
                    "provider_config": schema.provider_config,
                    "content_hash": content_hash,
                    "is_active": make_active,
                }
            )
            await self.audit.append(
                entity_type="PromptVersion",
                entity_id=version.id,
                action="CREATE",
                ctx=self.ctx,
                before_state=_version_state(previous) if previous and make_active else None,
                after_state=_version_state(version),
                content_hash=content_hash,
            )
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConcurrencyError(
                "Concurrent version creation conflict",
                {"semantic_version": schema.semantic_version},
            ) from exc
        return version

    async def list_versions(self, prompt_id: uuid.UUID) -> list[PromptVersion]:
        await self.get_prompt(prompt_id)
        return await self.versions.get_versions_by_prompt(prompt_id)

    async def get_version(self, prompt_id: uuid.UUID, version_id: uuid.UUID) -> PromptVersion:
        version = await self.versions.get(version_id)
        if not version or version.prompt_id != prompt_id:
            raise EntityNotFoundException("Prompt version not found for this prompt.")
        return version

    async def _transition(
        self, prompt_id: uuid.UUID, target_version_id: uuid.UUID, action: str
    ) -> PromptVersion:
        """Change which version is active. Never touches version content."""
        if not await self.prompts.get_for_update(prompt_id):
            raise EntityNotFoundException(f"Prompt '{prompt_id}' was not found.")
        target = await self.versions.get(target_version_id)
        if not target or target.prompt_id != prompt_id:
            raise EntityNotFoundException(
                "Target prompt version does not exist or does not belong to this prompt.",
                {"target_version_id": str(target_version_id)},
            )
        current = await self.versions.get_active_version(prompt_id)
        if current and current.id == target.id:
            raise ValidationError("Target version is already active.")
        if action == "ROLLBACK" and current is None:
            raise ValidationError("There is no active version to roll back from.")
        before = _version_state(current) if current else None
        await self.versions.set_active(prompt_id, target.id)
        await self.db.refresh(target)
        await self.audit.append(
            entity_type="PromptVersion",
            entity_id=target.id,
            action=action,
            ctx=self.ctx,
            before_state=before,
            after_state=_version_state(target),
            content_hash=target.content_hash,
        )
        await self.db.commit()
        return target

    async def activate_version(self, prompt_id: uuid.UUID, version_id: uuid.UUID) -> PromptVersion:
        return await self._transition(prompt_id, version_id, "ACTIVATE")

    async def rollback_prompt_version(
        self, prompt_id: uuid.UUID, target_version_id: uuid.UUID
    ) -> PromptVersion:
        return await self._transition(prompt_id, target_version_id, "ROLLBACK")

    async def verify_version_integrity(
        self, prompt_id: uuid.UUID, version_id: uuid.UUID
    ) -> dict[str, Any]:
        version = await self.get_version(prompt_id, version_id)
        computed = compute_content_hash(
            prompt_id=version.prompt_id,
            semantic_version=version.semantic_version,
            template=version.template,
            metadata=version.metadata_json,
            provider_config=version.provider_config,
        )
        return {
            "version_id": version.id,
            "stored_hash": version.content_hash,
            "computed_hash": computed,
            "intact": computed == version.content_hash,
        }

    # ---- read models -------------------------------------------------------------------------
    async def get_prompt_diff(
        self,
        prompt_id: uuid.UUID,
        version_a_id: uuid.UUID,
        version_b_id: uuid.UUID,
        *,
        granularity: str = "token",
        tokenizer: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        a = await self.get_version(prompt_id, version_a_id)
        b = await self.get_version(prompt_id, version_b_id)
        try:
            diff = diff_texts(
                a.template,
                b.template,
                granularity=granularity,  # type: ignore[arg-type]
                model=model,
                provider=provider,
                tokenizer_name=tokenizer,
            )
        except ValueError as exc:  # unknown tiktoken encoding name
            raise ValidationError(str(exc)) from exc
        vars_a, vars_b = set(extract_variables(a.template)), set(extract_variables(b.template))
        return {
            "prompt_id": prompt_id,
            "version_a": a,
            "version_b": b,
            "template_diff": diff.to_dict(),
            "variables": {
                "added": sorted(vars_b - vars_a),
                "removed": sorted(vars_a - vars_b),
                "unchanged": sorted(vars_a & vars_b),
            },
            "config_diff": _dict_diff(a.provider_config, b.provider_config),
            "metadata_diff": _dict_diff(a.metadata_json, b.metadata_json),
        }

    async def get_changelog(self, prompt_id: uuid.UUID) -> list[dict[str, Any]]:
        await self.get_prompt(prompt_id)
        versions = await self.versions.get_versions_by_prompt(prompt_id)
        ordered = sorted(versions, key=lambda v: SemanticVersion.from_string(v.semantic_version))
        entries: list[dict[str, Any]] = []
        previous: PromptVersion | None = None
        for v in ordered:
            entry: dict[str, Any] = {
                "version_id": v.id,
                "semantic_version": v.semantic_version,
                "content_hash": v.content_hash,
                "is_active": v.is_active,
                "created_at": v.created_at,
                "previous_version": previous.semantic_version if previous else None,
                "diff_stats": None,
                "tokenizer": None,
            }
            if previous:
                diff = diff_texts(previous.template, v.template)
                entry["diff_stats"] = diff.stats
                entry["tokenizer"] = diff.tokenizer
            entries.append(entry)
            previous = v
        return entries

    async def get_audit_history(self, prompt_id: uuid.UUID, limit: int = 200) -> list[AuditLog]:
        await self.get_prompt(prompt_id)
        version_ids = (
            (
                await self.db.execute(
                    select(PromptVersion.id).where(PromptVersion.prompt_id == prompt_id)
                )
            )
            .scalars()
            .all()
        )
        return await self.audit.list_events(entity_ids=[prompt_id, *version_ids], limit=limit)


def _dict_diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in sorted(set(a) | set(b)):
        if a.get(key) != b.get(key):
            out[key] = {"before": a.get(key), "after": b.get(key)}
    return out
