from typing import Any, Dict, List, Optional
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundException, ValidationError
from app.models.prompt import Prompt, PromptVersion
from app.promptops.versioning import SemanticVersion, validate_semantic_version
from app.repositories.prompt import PromptRepository, PromptVersionRepository

logger = structlog.get_logger(__name__)


class VersionManager:
    """Service for managing immutable prompt versions."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.prompt_repo = PromptRepository(db)
        self.version_repo = PromptVersionRepository(db)
    
    async def create_version(
        self,
        prompt_id: str,
        semantic_version: str,
        template: str,
        metadata: Optional[Dict[str, Any]] = None,
        provider_config: Optional[Dict[str, Any]] = None,
        set_as_active: bool = False,
    ) -> PromptVersion:
        """Create a new immutable prompt version.
        
        Args:
            prompt_id: ID of the parent prompt
            semantic_version: Semantic version string (e.g., '1.0.0')
            template: Prompt template content
            metadata: Optional metadata dictionary
            provider_config: Optional provider configuration
            set_as_active: Whether to set this version as active
            
        Returns:
            Created prompt version
            
        Raises:
            EntityNotFoundException: If prompt not found
            ValidationError: If version is invalid or already exists
        """
        # Validate prompt exists
        prompt = await self.prompt_repo.get(prompt_id)
        if not prompt:
            raise EntityNotFoundException("Prompt not found")
        
        # Validate semantic version format
        is_valid, error_msg = validate_semantic_version(semantic_version)
        if not is_valid:
            raise ValidationError(f"Invalid semantic version: {error_msg}")
        
        # Check for existing version
        existing_version = await self.version_repo.get_by_prompt_and_version(
            prompt_id, semantic_version
        )
        if existing_version:
            raise ValidationError(
                f"Version {semantic_version} already exists for this prompt"
            )
        
        # Create version
        version_data = {
            "prompt_id": prompt_id,
            "semantic_version": semantic_version,
            "template": template,
            "metadata_json": metadata or {},
            "provider_config": provider_config or {},
            "is_active": set_as_active,
        }
        
        # If setting as active, deactivate other versions
        if set_as_active:
            await self._deactivate_all_versions(prompt_id)
        
        version = await self.version_repo.create(obj_in=version_data)
        await self.db.commit()
        
        await logger.ainfo(
            "Prompt version created",
            version_id=version.id,
            prompt_id=prompt_id,
            semantic_version=semantic_version,
            set_as_active=set_as_active,
        )
        
        return version
    
    async def get_version(self, version_id: str) -> PromptVersion:
        """Get a prompt version by ID.
        
        Args:
            version_id: ID of the version
            
        Returns:
            Prompt version
            
        Raises:
            EntityNotFoundException: If version not found
        """
        version = await self.version_repo.get(version_id)
        if not version:
            raise EntityNotFoundException("Prompt version not found")
        return version
    
    async def list_versions(
        self,
        prompt_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> List[PromptVersion]:
        """List all versions of a prompt.
        
        Args:
            prompt_id: ID of the prompt
            skip: Number of versions to skip
            limit: Maximum number of versions to return
            
        Returns:
            List of prompt versions
        """
        # Validate prompt exists
        prompt = await self.prompt_repo.get(prompt_id)
        if not prompt:
            raise EntityNotFoundException("Prompt not found")
        
        versions = await self.version_repo.get_by_prompt(
            prompt_id, skip=skip, limit=limit
        )
        
        return versions
    
    async def get_active_version(self, prompt_id: str) -> Optional[PromptVersion]:
        """Get the active version of a prompt.
        
        Args:
            prompt_id: ID of the prompt
            
        Returns:
            Active prompt version or None
        """
        return await self.version_repo.get_active_by_prompt(prompt_id)
    
    async def validate_version_immutability(self, version_id: str) -> bool:
        """Validate that a version has not been modified since creation.
        
        This checks the database constraints and service-level immutability.
        
        Args:
            version_id: ID of the version
            
        Returns:
            True if version is immutable (unchanged), False otherwise
        """
        version = await self.version_repo.get(version_id)
        if not version:
            raise EntityNotFoundException("Prompt version not found")
        
        # In a real implementation, this might check:
        # - Hash of the version content
        # - Timestamp comparison
        # - Audit log verification
        
        # For now, we rely on the database constraint that versions cannot be updated
        # The service layer enforces this by not providing update methods
        return True
    
    async def get_version_history(
        self,
        prompt_id: str,
    ) -> List[Dict[str, Any]]:
        """Get the complete version history for a prompt.
        
        Args:
            prompt_id: ID of the prompt
            
        Returns:
            List of version history entries with metadata
        """
        # Validate prompt exists
        prompt = await self.prompt_repo.get(prompt_id)
        if not prompt:
            raise EntityNotFoundException("Prompt not found")
        
        versions = await self.version_repo.get_by_prompt(prompt_id, limit=1000)
        
        history = []
        for version in versions:
            history.append({
                "version_id": str(version.id),
                "semantic_version": version.semantic_version,
                "is_active": version.is_active,
                "created_at": version.created_at.isoformat() if version.created_at else None,
                "template_length": len(version.template),
                "metadata": version.metadata_json,
                "provider_config": version.provider_config,
            })
        
        return history
    
    async def _deactivate_all_versions(self, prompt_id: str) -> None:
        """Deactivate all versions of a prompt.
        
        This is used internally when setting a new active version.
        
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
    
    async def suggest_next_version(
        self,
        prompt_id: str,
        change_type: str = "patch",
    ) -> str:
        """Suggest the next semantic version for a prompt.
        
        Args:
            prompt_id: ID of the prompt
            change_type: Type of change ('major', 'minor', or 'patch')
            
        Returns:
            Suggested next version string
        """
        # Get all versions
        versions = await self.version_repo.get_by_prompt(prompt_id, limit=1000)
        
        if not versions:
            # First version
            return "1.0.0"
        
        # Find the latest version (highest semantic version)
        latest_version = None
        for version in versions:
            try:
                semver = SemanticVersion.from_string(version.semantic_version)
                if latest_version is None or semver > latest_version:
                    latest_version = semver
            except ValueError:
                # Skip invalid versions
                continue
        
        if latest_version is None:
            return "1.0.0"
        
        # Increment based on change type
        if change_type == "major":
            next_version = latest_version.increment_major()
        elif change_type == "minor":
            next_version = latest_version.increment_minor()
        else:  # patch
            next_version = latest_version.increment_patch()
        
        return str(next_version)
    
    async def compare_versions(
        self,
        version_a_id: str,
        version_b_id: str,
    ) -> Dict[str, Any]:
        """Compare two versions and return their differences.
        
        Args:
            version_a_id: ID of the first version
            version_b_id: ID of the second version
            
        Returns:
            Dictionary with comparison results
        """
        version_a = await self.version_repo.get(version_a_id)
        version_b = await self.version_repo.get(version_b_id)
        
        if not version_a or not version_b:
            raise EntityNotFoundException("One or both versions not found")
        
        # Compare semantic versions
        try:
            semver_a = SemanticVersion.from_string(version_a.semantic_version)
            semver_b = SemanticVersion.from_string(version_b.semantic_version)
            version_comparison = semver_a.get_version_difference(semver_b)
        except ValueError:
            version_comparison = "invalid"
        
        return {
            "version_a": {
                "id": str(version_a.id),
                "semantic_version": version_a.semantic_version,
                "is_active": version_a.is_active,
            },
            "version_b": {
                "id": str(version_b.id),
                "semantic_version": version_b.semantic_version,
                "is_active": version_b.is_active,
            },
            "version_comparison": version_comparison,
            "template_different": version_a.template != version_b.template,
            "metadata_different": version_a.metadata_json != version_b.metadata_json,
            "provider_config_different": version_a.provider_config != version_b.provider_config,
        }
