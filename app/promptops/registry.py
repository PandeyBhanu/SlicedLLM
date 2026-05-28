from typing import Any, Dict, List, Optional
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundException, ValidationError
from app.models.prompt import Prompt, PromptVersion
from app.promptops.versioning import SemanticVersion, validate_semantic_version
from app.repositories.prompt import PromptRepository, PromptVersionRepository

logger = structlog.get_logger(__name__)


class PromptRegistry:
    """Registry service for managing prompts with metadata tagging."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.prompt_repo = PromptRepository(db)
        self.version_repo = PromptVersionRepository(db)
    
    async def create_prompt(
        self,
        name: str,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Prompt:
        """Create a new prompt with optional tags.
        
        Args:
            name: Unique name for the prompt
            description: Optional description
            tags: Optional list of tags for categorization
            
        Returns:
            Created prompt
            
        Raises:
            ValidationError: If prompt name already exists
        """
        # Check for existing prompt
        existing = await self.prompt_repo.get_by_name(name)
        if existing:
            raise ValidationError(f"Prompt with name '{name}' already exists")
        
        # Normalize tags
        normalized_tags = self._normalize_tags(tags or [])
        
        prompt_data = {
            "name": name,
            "description": description,
            "tags": normalized_tags,
        }
        
        prompt = await self.prompt_repo.create(obj_in=prompt_data)
        await self.db.commit()
        
        await logger.ainfo(
            "Prompt created",
            prompt_id=prompt.id,
            name=name,
            tags=normalized_tags,
        )
        
        return prompt
    
    async def update_prompt(
        self,
        prompt_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Prompt:
        """Update prompt metadata (not versions).
        
        Args:
            prompt_id: ID of the prompt to update
            name: Optional new name
            description: Optional new description
            tags: Optional new tags
            
        Returns:
            Updated prompt
            
        Raises:
            EntityNotFoundException: If prompt not found
            ValidationError: If new name conflicts with existing prompt
        """
        prompt = await self.prompt_repo.get(prompt_id)
        if not prompt:
            raise EntityNotFoundException("Prompt not found")
        
        update_data = {}
        
        if name is not None:
            existing = await self.prompt_repo.get_by_name(name)
            if existing and existing.id != prompt.id:
                raise ValidationError(f"Prompt with name '{name}' already exists")
            update_data["name"] = name
        
        if description is not None:
            update_data["description"] = description
        
        if tags is not None:
            update_data["tags"] = self._normalize_tags(tags)
        
        if update_data:
            prompt = await self.prompt_repo.update(prompt, obj_in=update_data)
            await self.db.commit()
            
            await logger.ainfo(
                "Prompt updated",
                prompt_id=prompt_id,
                update_data=update_data,
            )
        
        return prompt
    
    async def add_tags(self, prompt_id: str, tags: List[str]) -> Prompt:
        """Add tags to a prompt.
        
        Args:
            prompt_id: ID of the prompt
            tags: Tags to add
            
        Returns:
            Updated prompt
        """
        prompt = await self.prompt_repo.get(prompt_id)
        if not prompt:
            raise EntityNotFoundException("Prompt not found")
        
        current_tags = set(prompt.tags or [])
        new_tags = set(self._normalize_tags(tags))
        
        combined_tags = list(current_tags | new_tags)
        
        prompt = await self.prompt_repo.update(
            prompt,
            obj_in={"tags": combined_tags},
        )
        await self.db.commit()
        
        await logger.ainfo(
            "Tags added to prompt",
            prompt_id=prompt_id,
            added_tags=list(new_tags),
        )
        
        return prompt
    
    async def remove_tags(self, prompt_id: str, tags: List[str]) -> Prompt:
        """Remove tags from a prompt.
        
        Args:
            prompt_id: ID of the prompt
            tags: Tags to remove
            
        Returns:
            Updated prompt
        """
        prompt = await self.prompt_repo.get(prompt_id)
        if not prompt:
            raise EntityNotFoundException("Prompt not found")
        
        current_tags = set(prompt.tags or [])
        tags_to_remove = set(self._normalize_tags(tags))
        
        remaining_tags = list(current_tags - tags_to_remove)
        
        prompt = await self.prompt_repo.update(
            prompt,
            obj_in={"tags": remaining_tags},
        )
        await self.db.commit()
        
        await logger.ainfo(
            "Tags removed from prompt",
            prompt_id=prompt_id,
            removed_tags=list(tags_to_remove),
        )
        
        return prompt
    
    async def search_by_tags(self, tags: List[str], match_all: bool = False) -> List[Prompt]:
        """Search prompts by tags.
        
        Args:
            tags: Tags to search for
            match_all: If True, require all tags; if False, match any tag
            
        Returns:
            List of matching prompts
        """
        prompts = await self.prompt_repo.get_multi()
        
        normalized_search_tags = set(self._normalize_tags(tags))
        
        matching_prompts = []
        for prompt in prompts:
            prompt_tags = set(prompt.tags or [])
            
            if match_all:
                if normalized_search_tags.issubset(prompt_tags):
                    matching_prompts.append(prompt)
            else:
                if normalized_search_tags & prompt_tags:
                    matching_prompts.append(prompt)
        
        await logger.adebug(
            "Prompt search by tags",
            search_tags=tags,
            match_all=match_all,
            results_count=len(matching_prompts),
        )
        
        return matching_prompts
    
    async def get_all_tags(self) -> List[str]:
        """Get all unique tags across all prompts.
        
        Returns:
            List of unique tags
        """
        prompts = await self.prompt_repo.get_multi()
        
        all_tags = set()
        for prompt in prompts:
            if prompt.tags:
                all_tags.update(prompt.tags)
        
        return sorted(list(all_tags))
    
    def _normalize_tags(self, tags: List[str]) -> List[str]:
        """Normalize tags for consistency.
        
        Args:
            tags: Raw tags
            
        Returns:
            Normalized tags (lowercase, trimmed, deduplicated)
        """
        normalized = set()
        for tag in tags:
            if tag:
                normalized.add(tag.strip().lower())
        
        return sorted(list(normalized))
    
    async def get_prompt_statistics(self, prompt_id: str) -> Dict[str, Any]:
        """Get statistics for a prompt.
        
        Args:
            prompt_id: ID of the prompt
            
        Returns:
            Dictionary with prompt statistics
        """
        prompt = await self.prompt_repo.get_with_versions(prompt_id)
        if not prompt:
            raise EntityNotFoundException("Prompt not found")
        
        versions = prompt.versions or []
        
        # Count active version
        active_version = next((v for v in versions if v.is_active), None)
        
        # Get version statistics
        version_count = len(versions)
        
        # Get latest version
        latest_version = versions[0] if versions else None
        
        return {
            "prompt_id": prompt.id,
            "name": prompt.name,
            "description": prompt.description,
            "tags": prompt.tags,
            "total_versions": version_count,
            "active_version_id": active_version.id if active_version else None,
            "active_version": active_version.semantic_version if active_version else None,
            "latest_version_id": latest_version.id if latest_version else None,
            "latest_version": latest_version.semantic_version if latest_version else None,
            "created_at": prompt.created_at.isoformat() if prompt.created_at else None,
            "updated_at": prompt.updated_at.isoformat() if prompt.updated_at else None,
        }
