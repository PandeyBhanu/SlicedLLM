import difflib
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundException, ValidationError
from app.models.audit import AuditLog
from app.models.prompt import Prompt, PromptVersion
from app.repositories.audit import AuditLogRepository
from app.repositories.prompt import PromptRepository, PromptVersionRepository
from app.schemas.prompt import (
    PromptCreate,
    PromptDiffResponse,
    PromptVersionCreate,
)

logger = structlog.get_logger(__name__)


class PromptService:
    """Manages the lifecycle of Prompts, semantic versioning, diffs, and releases."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.prompt_repo = PromptRepository(db)
        self.version_repo = PromptVersionRepository(db)
        self.audit_repo = AuditLogRepository(db)

    async def _write_audit_log(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        before_state: Optional[Dict[str, Any]] = None,
        after_state: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        """Helper to create and write an audit trace."""
        audit_payload = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "before_state": before_state,
            "after_state": after_state,
        }
        return await self.audit_repo.create(obj_in=audit_payload)

    async def create_prompt(self, schema: PromptCreate) -> Prompt:
        """Create a new prompt container with auditing."""
        existing = await self.prompt_repo.get_by_name(schema.name)
        if existing:
            raise ValidationError(
                message=f"Prompt with name '{schema.name}' already exists.",
                details={"name": schema.name},
            )

        # Transaction boundary
        async with self.db.begin_nested():
            prompt = await self.prompt_repo.create(obj_in=schema.model_dump())
            await self._write_audit_log(
                entity_type="Prompt",
                entity_id=prompt.id,
                action="CREATE",
                after_state={"name": prompt.name, "description": prompt.description},
            )
        
        await self.db.commit()
        await logger.ainfo("Prompt created successfully", id=prompt.id, name=prompt.name)
        return prompt

    async def get_prompt(self, id: uuid.UUID) -> Prompt:
        """Fetch prompt container with historical versions."""
        prompt = await self.prompt_repo.get(id)
        if not prompt:
            raise EntityNotFoundException(
                message=f"Prompt with ID '{id}' was not found.",
                details={"id": str(id)},
            )
        # Force loading versions
        versions = await self.version_repo.get_versions_by_prompt(id)
        prompt.versions = versions
        return prompt

    async def get_all_prompts(self, skip: int = 0, limit: int = 100) -> List[Prompt]:
        """List all prompts."""
        return await self.prompt_repo.get_multi(skip=skip, limit=limit)

    async def create_prompt_version(
        self, prompt_id: uuid.UUID, schema: PromptVersionCreate
    ) -> PromptVersion:
        """Create and publish an immutable new prompt version."""
        prompt = await self.prompt_repo.get(prompt_id)
        if not prompt:
            raise EntityNotFoundException(
                message=f"Prompt with ID '{prompt_id}' was not found.",
                details={"prompt_id": str(prompt_id)},
            )

        # Enforce version uniqueness for this specific prompt
        existing_version = await self.version_repo.get_by_version(
            prompt_id, schema.semantic_version
        )
        if existing_version:
            raise ValidationError(
                message=f"Version '{schema.semantic_version}' already exists for this prompt.",
                details={
                    "prompt_id": str(prompt_id),
                    "semantic_version": schema.semantic_version,
                },
            )

        # If it's the first version, make it active by default
        active_version = await self.version_repo.get_active_version(prompt_id)
        is_first_version = active_version is None

        async with self.db.begin_nested():
            # If the new version is going to be active, deactivate others
            if is_first_version:
                await self.version_repo.deactivate_all_versions(prompt_id)

            version_data = schema.model_dump()
            version_data["prompt_id"] = prompt_id
            version_data["is_active"] = is_first_version

            version = await self.version_repo.create(obj_in=version_data)

            before_state = None
            if active_version:
                before_state = {
                    "version_id": str(active_version.id),
                    "semantic_version": active_version.semantic_version,
                }

            await self._write_audit_log(
                entity_type="PromptVersion",
                entity_id=version.id,
                action="CREATE",
                before_state=before_state,
                after_state={
                    "semantic_version": version.semantic_version,
                    "template": version.template,
                    "is_active": version.is_active,
                },
            )

        await self.db.commit()
        await logger.ainfo(
            "Prompt version created",
            prompt_id=prompt_id,
            version_id=version.id,
            version=version.semantic_version,
            is_active=version.is_active,
        )
        return version

    async def rollback_prompt_version(
        self, prompt_id: uuid.UUID, target_version_id: uuid.UUID
    ) -> PromptVersion:
        """Rollback active status to a former version without deleting historical state."""
        prompt = await self.prompt_repo.get(prompt_id)
        if not prompt:
            raise EntityNotFoundException(
                message=f"Prompt with ID '{prompt_id}' was not found."
            )

        target_version = await self.version_repo.get(target_version_id)
        if not target_version or target_version.prompt_id != prompt_id:
            raise EntityNotFoundException(
                message="Target prompt version does not exist or does not belong to this prompt.",
                details={"target_version_id": str(target_version_id)},
            )

        current_active = await self.version_repo.get_active_version(prompt_id)
        if current_active and current_active.id == target_version_id:
            # Already active, no action needed
            return current_active

        async with self.db.begin_nested():
            # Deactivate current release versions
            await self.version_repo.deactivate_all_versions(prompt_id)
            
            # Activate target version
            target_version.is_active = True
            self.db.add(target_version)
            await self.db.flush()

            before_state = (
                {
                    "version_id": str(current_active.id),
                    "semantic_version": current_active.semantic_version,
                }
                if current_active
                else None
            )

            await self._write_audit_log(
                entity_type="Prompt",
                entity_id=prompt_id,
                action="ROLLBACK",
                before_state=before_state,
                after_state={
                    "active_version_id": str(target_version.id),
                    "semantic_version": target_version.semantic_version,
                },
            )

        await self.db.commit()
        await logger.ainfo(
            "Prompt rolled back successfully",
            prompt_id=prompt_id,
            active_version_id=target_version.id,
            semantic_version=target_version.semantic_version,
        )
        return target_version

    async def get_prompt_diff(
        self, prompt_id: uuid.UUID, version_a_id: uuid.UUID, version_b_id: uuid.UUID
    ) -> PromptDiffResponse:
        """Produce unified template diffs and parameter metadata config diffs."""
        version_a = await self.version_repo.get(version_a_id)
        version_b = await self.version_repo.get(version_b_id)

        if not version_a or version_a.prompt_id != prompt_id:
            raise EntityNotFoundException(message="Version A not found or invalid.")
        if not version_b or version_b.prompt_id != prompt_id:
            raise EntityNotFoundException(message="Version B not found or invalid.")

        # Compute line diff of template strings
        lines_a = version_a.template.splitlines(keepends=True)
        lines_b = version_b.template.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            lines_a,
            lines_b,
            fromfile=f"v{version_a.semantic_version}",
            tofile=f"v{version_b.semantic_version}",
        )
        template_diff = "".join(diff)

        # Compute simple config changes
        config_diff = {}
        all_keys = set(version_a.provider_config.keys()) | set(version_b.provider_config.keys())
        for key in all_keys:
            val_a = version_a.provider_config.get(key)
            val_b = version_b.provider_config.get(key)
            if val_a != val_b:
                config_diff[key] = {"before": val_a, "after": val_b}

        return PromptDiffResponse(
            prompt_id=prompt_id,
            version_a=version_a.semantic_version,
            version_b=version_b.semantic_version,
            template_diff=template_diff,
            config_diff=config_diff,
        )
