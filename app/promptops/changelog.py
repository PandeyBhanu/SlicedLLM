from typing import Any, Dict, List, Optional
from datetime import datetime
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundException
from app.models.prompt import Prompt, PromptVersion
from app.promptops.diff import PromptDiffEngine
from app.repositories.prompt import PromptRepository, PromptVersionRepository

logger = structlog.get_logger(__name__)


class ChangelogEntry(BaseModel):
    """A single entry in the changelog."""
    
    version_id: str
    semantic_version: str
    timestamp: datetime
    change_type: str  # "created", "activated", "rollback", "modified"
    description: str
    changes: Dict[str, Any]
    previous_version_id: Optional[str] = None


class ChangelogService:
    """Service for generating and managing prompt changelogs."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.prompt_repo = PromptRepository(db)
        self.version_repo = PromptVersionRepository(db)
        self.diff_engine = PromptDiffEngine()
    
    async def generate_changelog(
        self,
        prompt_id: str,
        include_diffs: bool = True,
    ) -> List[Dict[str, Any]]:
        """Generate a changelog for a prompt.
        
        Args:
            prompt_id: ID of the prompt
            include_diffs: Whether to include diff information between versions
            
        Returns:
            List of changelog entries
        """
        # Validate prompt exists
        prompt = await self.prompt_repo.get(prompt_id)
        if not prompt:
            raise EntityNotFoundException("Prompt not found")
        
        # Get all versions sorted by creation time
        versions = await self.version_repo.get_by_prompt(prompt_id, limit=1000)
        
        if not versions:
            return []
        
        changelog = []
        previous_version = None
        
        for i, version in enumerate(versions):
            entry = {
                "version_id": str(version.id),
                "semantic_version": version.semantic_version,
                "timestamp": version.created_at.isoformat() if version.created_at else None,
                "is_active": version.is_active,
                "change_type": "created" if i == 0 else "modified",
                "description": self._generate_change_description(version, previous_version),
                "metadata": version.metadata_json,
                "provider_config": version.provider_config,
            }
            
            # Add diff information if requested and there's a previous version
            if include_diffs and previous_version:
                diff_result = self.diff_engine.diff_with_variables(
                    previous_version.template,
                    version.template,
                )
                entry["diff"] = diff_result
            
            changelog.append(entry)
            previous_version = version
        
        return changelog
    
    async def get_version_diff(
        self,
        version_a_id: str,
        version_b_id: str,
    ) -> Dict[str, Any]:
        """Get a detailed diff between two versions.
        
        Args:
            version_a_id: ID of the first version
            version_b_id: ID of the second version
            
        Returns:
            Detailed diff information
        """
        version_a = await self.version_repo.get(version_a_id)
        version_b = await self.version_repo.get(version_b_id)
        
        if not version_a or not version_b:
            raise EntityNotFoundException("One or both versions not found")
        
        # Generate diff
        diff_result = self.diff_engine.diff_with_variables(
            version_a.template,
            version_b.template,
        )
        
        return {
            "version_a": {
                "id": str(version_a.id),
                "semantic_version": version_a.semantic_version,
                "is_active": version_a.is_active,
                "created_at": version_a.created_at.isoformat() if version_a.created_at else None,
            },
            "version_b": {
                "id": str(version_b.id),
                "semantic_version": version_b.semantic_version,
                "is_active": version_b.is_active,
                "created_at": version_b.created_at.isoformat() if version_b.created_at else None,
            },
            "diff": diff_result,
        }
    
    async def get_latest_changes(
        self,
        prompt_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get the latest changes for a prompt.
        
        Args:
            prompt_id: ID of the prompt
            limit: Maximum number of changes to return
            
        Returns:
            List of recent changes
        """
        changelog = await self.generate_changelog(prompt_id, include_diffs=False)
        return changelog[:limit]
    
    async def get_change_summary(
        self,
        prompt_id: str,
    ) -> Dict[str, Any]:
        """Get a summary of changes for a prompt.
        
        Args:
            prompt_id: ID of the prompt
            
        Returns:
            Summary statistics
        """
        # Validate prompt exists
        prompt = await self.prompt_repo.get(prompt_id)
        if not prompt:
            raise EntityNotFoundException("Prompt not found")
        
        # Get all versions
        versions = await self.version_repo.get_by_prompt(prompt_id, limit=1000)
        
        if not versions:
            return {
                "prompt_id": prompt_id,
                "total_versions": 0,
                "active_version": None,
                "latest_version": None,
                "total_changes": 0,
            }
        
        # Calculate statistics
        total_versions = len(versions)
        active_version = next((v for v in versions if v.is_active), None)
        latest_version = versions[0] if versions else None
        
        # Count significant changes (versions with template changes)
        significant_changes = 0
        previous_template = None
        for version in reversed(versions):
            if previous_template and version.template != previous_template:
                significant_changes += 1
            previous_template = version.template
        
        return {
            "prompt_id": prompt_id,
            "prompt_name": prompt.name,
            "total_versions": total_versions,
            "active_version": {
                "id": str(active_version.id),
                "semantic_version": active_version.semantic_version,
            } if active_version else None,
            "latest_version": {
                "id": str(latest_version.id),
                "semantic_version": latest_version.semantic_version,
            } if latest_version else None,
            "total_changes": significant_changes,
            "first_version": versions[-1].semantic_version if versions else None,
            "last_updated": versions[0].created_at.isoformat() if versions and versions[0].created_at else None,
        }
    
    def _generate_change_description(
        self,
        version: PromptVersion,
        previous_version: Optional[PromptVersion],
    ) -> str:
        """Generate a human-readable description of changes.
        
        Args:
            version: Current version
            previous_version: Previous version (if any)
            
        Returns:
            Description string
        """
        if not previous_version:
            return f"Initial version {version.semantic_version} created"
        
        # Compare with previous version
        changes = []
        
        if version.template != previous_version.template:
            changes.append("template updated")
        
        if version.metadata_json != previous_version.metadata_json:
            changes.append("metadata updated")
        
        if version.provider_config != previous_version.provider_config:
            changes.append("provider configuration updated")
        
        if version.is_active and not previous_version.is_active:
            changes.append("activated")
        
        if not changes:
            return f"Version {version.semantic_version} created (no content changes)"
        
        return f"Version {version.semantic_version}: {', '.join(changes)}"
