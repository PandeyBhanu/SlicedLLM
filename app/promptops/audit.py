import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.prompt import Prompt, PromptVersion
from app.repositories.audit import AuditLogRepository
from app.repositories.prompt import PromptRepository, PromptVersionRepository

logger = structlog.get_logger(__name__)


class PromptOpsAuditService:
    """Enhanced audit service for PromptOps operations with state snapshots."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit_repo = AuditLogRepository(db)
        self.prompt_repo = PromptRepository(db)
        self.version_repo = PromptVersionRepository(db)
    
    async def log_prompt_creation(
        self,
        prompt: Prompt,
        created_by: Optional[str] = None,
    ) -> AuditLog:
        """Log prompt creation with state snapshot.
        
        Args:
            prompt: The created prompt
            created_by: Optional identifier of who created the prompt
            
        Returns:
            Created audit log entry
        """
        after_state = self._serialize_prompt(prompt)
        
        audit_log = await self.audit_repo.create(obj_in={
            "entity_type": "Prompt",
            "entity_id": prompt.id,
            "action": "CREATE",
            "before_state": None,
            "after_state": after_state,
        })
        
        await self.db.commit()
        
        await logger.ainfo(
            "Prompt creation audited",
            prompt_id=prompt.id,
            name=prompt.name,
            audit_log_id=audit_log.id,
        )
        
        return audit_log
    
    async def log_prompt_update(
        self,
        prompt: Prompt,
        previous_state: Dict[str, Any],
        updated_by: Optional[str] = None,
    ) -> AuditLog:
        """Log prompt update with before/after state snapshots.
        
        Args:
            prompt: The updated prompt
            previous_state: State before the update
            updated_by: Optional identifier of who updated the prompt
            
        Returns:
            Created audit log entry
        """
        after_state = self._serialize_prompt(prompt)
        
        audit_log = await self.audit_repo.create(obj_in={
            "entity_type": "Prompt",
            "entity_id": prompt.id,
            "action": "UPDATE",
            "before_state": previous_state,
            "after_state": after_state,
        })
        
        await self.db.commit()
        
        await logger.ainfo(
            "Prompt update audited",
            prompt_id=prompt.id,
            name=prompt.name,
            audit_log_id=audit_log.id,
        )
        
        return audit_log
    
    async def log_version_creation(
        self,
        version: PromptVersion,
        created_by: Optional[str] = None,
    ) -> AuditLog:
        """Log prompt version creation with state snapshot.
        
        Args:
            version: The created version
            created_by: Optional identifier of who created the version
            
        Returns:
            Created audit log entry
        """
        after_state = self._serialize_version(version)
        
        audit_log = await self.audit_repo.create(obj_in={
            "entity_type": "PromptVersion",
            "entity_id": version.id,
            "action": "CREATE",
            "before_state": None,
            "after_state": after_state,
        })
        
        await self.db.commit()
        
        await logger.ainfo(
            "Version creation audited",
            version_id=version.id,
            semantic_version=version.semantic_version,
            prompt_id=version.prompt_id,
            audit_log_id=audit_log.id,
        )
        
        return audit_log
    
    async def log_version_activation(
        self,
        version: PromptVersion,
        previous_active_version: Optional[PromptVersion],
        activated_by: Optional[str] = None,
    ) -> AuditLog:
        """Log version activation with before/after state snapshots.
        
        Args:
            version: The activated version
            previous_active_version: The previously active version (if any)
            activated_by: Optional identifier of who activated the version
            
        Returns:
            Created audit log entry
        """
        after_state = self._serialize_version(version)
        before_state = (
            self._serialize_version(previous_active_version)
            if previous_active_version
            else None
        )
        
        audit_log = await self.audit_repo.create(obj_in={
            "entity_type": "PromptVersion",
            "entity_id": version.id,
            "action": "ACTIVATE",
            "before_state": before_state,
            "after_state": after_state,
        })
        
        await self.db.commit()
        
        await logger.ainfo(
            "Version activation audited",
            version_id=version.id,
            semantic_version=version.semantic_version,
            prompt_id=version.prompt_id,
            previous_version=previous_active_version.semantic_version if previous_active_version else None,
            audit_log_id=audit_log.id,
        )
        
        return audit_log
    
    async def log_version_rollback(
        self,
        version: PromptVersion,
        from_version: PromptVersion,
        rolled_back_by: Optional[str] = None,
    ) -> AuditLog:
        """Log version rollback with before/after state snapshots.
        
        Args:
            version: The version rolled back to
            from_version: The version being rolled back from
            rolled_back_by: Optional identifier of who performed the rollback
            
        Returns:
            Created audit log entry
        """
        after_state = self._serialize_version(version)
        before_state = self._serialize_version(from_version)
        
        audit_log = await self.audit_repo.create(obj_in={
            "entity_type": "PromptVersion",
            "entity_id": version.id,
            "action": "ROLLBACK",
            "before_state": before_state,
            "after_state": after_state,
        })
        
        await self.db.commit()
        
        await logger.ainfo(
            "Version rollback audited",
            version_id=version.id,
            semantic_version=version.semantic_version,
            prompt_id=version.prompt_id,
            from_version=from_version.semantic_version,
            audit_log_id=audit_log.id,
        )
        
        return audit_log
    
    async def get_prompt_audit_history(
        self,
        prompt_id: uuid.UUID,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get complete audit history for a prompt.
        
        Args:
            prompt_id: ID of the prompt
            limit: Maximum number of audit entries to return
            
        Returns:
            List of audit history entries
        """
        # Get prompt audit logs
        prompt_logs = await self.audit_repo.get_by_entity("Prompt", prompt_id)
        
        # Get all versions for this prompt
        versions = await self.version_repo.get_by_prompt(str(prompt_id), limit=1000)
        
        # Get version audit logs
        version_logs = []
        for version in versions:
            version_audit_logs = await self.audit_repo.get_by_entity(
                "PromptVersion", version.id
            )
            version_logs.extend(version_audit_logs)
        
        # Combine and sort by timestamp
        all_logs = prompt_logs + version_logs
        all_logs.sort(key=lambda x: x.created_at or datetime.min, reverse=True)
        
        # Format for response
        history = []
        for log in all_logs[:limit]:
            history.append({
                "audit_log_id": str(log.id),
                "entity_type": log.entity_type,
                "entity_id": str(log.entity_id),
                "action": log.action,
                "timestamp": log.created_at.isoformat() if log.created_at else None,
                "before_state": log.before_state,
                "after_state": log.after_state,
            })
        
        return history
    
    async def get_version_audit_history(
        self,
        version_id: uuid.UUID,
    ) -> List[Dict[str, Any]]:
        """Get audit history for a specific version.
        
        Args:
            version_id: ID of the version
            
        Returns:
            List of audit history entries
        """
        logs = await self.audit_repo.get_by_entity("PromptVersion", version_id)
        
        history = []
        for log in logs:
            history.append({
                "audit_log_id": str(log.id),
                "entity_type": log.entity_type,
                "entity_id": str(log.entity_id),
                "action": log.action,
                "timestamp": log.created_at.isoformat() if log.created_at else None,
                "before_state": log.before_state,
                "after_state": log.after_state,
            })
        
        return history
    
    def _serialize_prompt(self, prompt: Prompt) -> Dict[str, Any]:
        """Serialize a prompt to a dictionary for audit logging.
        
        Args:
            prompt: The prompt to serialize
            
        Returns:
            Serialized prompt state
        """
        return {
            "id": str(prompt.id),
            "name": prompt.name,
            "description": prompt.description,
            "tags": prompt.tags,
            "created_at": prompt.created_at.isoformat() if prompt.created_at else None,
            "updated_at": prompt.updated_at.isoformat() if prompt.updated_at else None,
        }
    
    def _serialize_version(self, version: PromptVersion) -> Dict[str, Any]:
        """Serialize a prompt version to a dictionary for audit logging.
        
        Args:
            version: The version to serialize
            
        Returns:
            Serialized version state
        """
        return {
            "id": str(version.id),
            "prompt_id": str(version.prompt_id),
            "semantic_version": version.semantic_version,
            "template": version.template,
            "template_hash": self._hash_template(version.template),
            "metadata": version.metadata_json,
            "provider_config": version.provider_config,
            "is_active": version.is_active,
            "created_at": version.created_at.isoformat() if version.created_at else None,
        }
    
    def _hash_template(self, template: str) -> str:
        """Generate a simple hash of the template for change detection.
        
        Args:
            template: The template to hash
            
        Returns:
            Hash string
        """
        import hashlib
        return hashlib.sha256(template.encode()).hexdigest()[:16]
