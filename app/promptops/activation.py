from typing import Any, Dict, Optional
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundException, ValidationError
from app.models.prompt import Prompt, PromptVersion
from app.repositories.prompt import PromptRepository, PromptVersionRepository
from app.promptops.version_manager import VersionManager

logger = structlog.get_logger(__name__)


class ActivationManager:
    """Service for managing prompt activation and rollback operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.prompt_repo = PromptRepository(db)
        self.version_repo = PromptVersionRepository(db)
        self.version_manager = VersionManager(db)
    
    async def activate_version(
        self,
        version_id: str,
        create_audit_log: bool = True,
    ) -> PromptVersion:
        """Activate a specific prompt version.
        
        This deactivates the currently active version and activates the specified version.
        Rollback creates a new active state without modifying existing versions.
        
        Args:
            version_id: ID of the version to activate
            create_audit_log: Whether to create an audit log entry
            
        Returns:
            The activated version
            
        Raises:
            EntityNotFoundException: If version not found
        """
        # Get the version to activate
        version = await self.version_repo.get(version_id)
        if not version:
            raise EntityNotFoundException("Prompt version not found")
        
        prompt_id = version.prompt_id
        
        # Get the currently active version for audit purposes
        current_active = await self.version_repo.get_active_by_prompt(prompt_id)
        
        # Deactivate all versions of this prompt
        await self._deactivate_all_versions(prompt_id)
        
        # Activate the specified version
        version = await self.version_repo.update(
            version,
            obj_in={"is_active": True},
        )
        
        await self.db.commit()
        
        await logger.ainfo(
            "Version activated",
            version_id=version_id,
            prompt_id=prompt_id,
            previous_active_id=str(current_active.id) if current_active else None,
        )
        
        # Create audit log if requested
        if create_audit_log and current_active:
            await self._create_activation_audit_log(
                prompt_id=prompt_id,
                previous_version_id=str(current_active.id),
                new_version_id=version_id,
            )
        
        return version
    
    async def rollback_to_version(
        self,
        version_id: str,
        create_audit_log: bool = True,
    ) -> PromptVersion:
        """Rollback to a specific version.
        
        This is essentially an activation operation but with semantic meaning
        of reverting to a previous state. The rollback creates a new active state
        without modifying or deleting any existing versions.
        
        Args:
            version_id: ID of the version to rollback to
            create_audit_log: Whether to create an audit log entry
            
        Returns:
            The activated version (rollback target)
            
        Raises:
            EntityNotFoundException: If version not found
        """
        # Get the version to rollback to
        version = await self.version_repo.get(version_id)
        if not version:
            raise EntityNotFoundException("Prompt version not found")
        
        prompt_id = version.prompt_id
        
        # Get the currently active version
        current_active = await self.version_repo.get_active_by_prompt(prompt_id)
        
        if current_active and current_active.id == version.id:
            raise ValidationError("Cannot rollback to the currently active version")
        
        # Perform the rollback (activation)
        activated_version = await self.activate_version(
            version_id=version_id,
            create_audit_log=False,  # We'll create our own audit log
        )
        
        # Create rollback-specific audit log
        if create_audit_log:
            await self._create_rollback_audit_log(
                prompt_id=prompt_id,
                from_version_id=str(current_active.id) if current_active else None,
                to_version_id=version_id,
            )
        
        await logger.ainfo(
            "Rollback completed",
            version_id=version_id,
            prompt_id=prompt_id,
            from_version=str(current_active.semantic_version) if current_active else None,
            to_version=version.semantic_version,
        )
        
        return activated_version
    
    async def rollback_to_semantic_version(
        self,
        prompt_id: str,
        semantic_version: str,
        create_audit_log: bool = True,
    ) -> PromptVersion:
        """Rollback to a version by semantic version string.
        
        Args:
            prompt_id: ID of the prompt
            semantic_version: Semantic version to rollback to (e.g., '1.0.0')
            create_audit_log: Whether to create an audit log entry
            
        Returns:
            The activated version
            
        Raises:
            EntityNotFoundException: If version not found
        """
        # Find the version by semantic version
        version = await self.version_repo.get_by_prompt_and_version(
            prompt_id, semantic_version
        )
        
        if not version:
            raise EntityNotFoundException(
                f"Version {semantic_version} not found for this prompt"
            )
        
        return await self.rollback_to_version(
            version_id=str(version.id),
            create_audit_log=create_audit_log,
        )
    
    async def get_rollback_candidates(
        self,
        prompt_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get candidates for rollback (previous versions).
        
        Args:
            prompt_id: ID of the prompt
            limit: Maximum number of candidates to return
            
        Returns:
            List of rollback candidates with metadata
        """
        # Get all versions
        versions = await self.version_repo.get_by_prompt(prompt_id, limit=limit)
        
        # Get current active version
        current_active = await self.version_repo.get_active_by_prompt(prompt_id)
        
        candidates = []
        for version in versions:
            # Skip the currently active version
            if current_active and version.id == current_active.id:
                continue
            
            candidates.append({
                "version_id": str(version.id),
                "semantic_version": version.semantic_version,
                "created_at": version.created_at.isoformat() if version.created_at else None,
                "is_previous_active": version.id != (current_active.id if current_active else None),
            })
        
        return candidates
    
    async def _deactivate_all_versions(self, prompt_id: str) -> None:
        """Deactivate all versions of a prompt.
        
        Args:
            prompt_id: ID of the prompt
        """
        versions = await self.version_repo.get_by_prompt(prompt_id, limit=1000)
        
        for version in versions:
            if version.is_active:
                await self.version_repo.update(
                    version,
                    obj_in={"is_active": False},
                )
    
    async def _create_activation_audit_log(
        self,
        prompt_id: str,
        previous_version_id: str,
        new_version_id: str,
    ) -> None:
        """Create an audit log entry for version activation.
        
        Args:
            prompt_id: ID of the prompt
            previous_version_id: ID of the previous active version
            new_version_id: ID of the newly activated version
        """
        # This would integrate with the audit system
        # For now, we'll log the action
        await logger.ainfo(
            "Activation audit log",
            prompt_id=prompt_id,
            previous_version_id=previous_version_id,
            new_version_id=new_version_id,
            action="activate_version",
        )
    
    async def _create_rollback_audit_log(
        self,
        prompt_id: str,
        from_version_id: Optional[str],
        to_version_id: str,
    ) -> None:
        """Create an audit log entry for rollback operation.
        
        Args:
            prompt_id: ID of the prompt
            from_version_id: ID of the version being rolled back from
            to_version_id: ID of the version being rolled back to
        """
        # This would integrate with the audit system
        # For now, we'll log the action
        await logger.ainfo(
            "Rollback audit log",
            prompt_id=prompt_id,
            from_version_id=from_version_id,
            to_version_id=to_version_id,
            action="rollback_version",
        )
    
    async def get_activation_history(
        self,
        prompt_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get the activation history for a prompt.
        
        This would typically query the audit log for activation events.
        For now, we'll return a placeholder structure.
        
        Args:
            prompt_id: ID of the prompt
            limit: Maximum number of history entries
            
        Returns:
            List of activation history entries
        """
        # Placeholder - in production, this would query the audit log
        return []
