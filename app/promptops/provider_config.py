from typing import Any, Dict, List, Optional
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundException, ValidationError
from app.models.prompt import Prompt, PromptVersion
from app.repositories.prompt import PromptRepository, PromptVersionRepository

logger = structlog.get_logger(__name__)


class ProviderConfigManager:
    """Service for managing provider configurations for prompts and versions."""
    
    # Default provider configurations
    DEFAULT_CONFIGS = {
        "ollama": {
            "temperature": 0.7,
            "max_tokens": None,
            "top_p": None,
            "frequency_penalty": None,
            "presence_penalty": None,
        },
        "groq": {
            "temperature": 0.7,
            "max_tokens": 1024,
            "top_p": 0.9,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
        },
        "openai": {
            "temperature": 0.7,
            "max_tokens": 1024,
            "top_p": 0.9,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
        },
    }
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.prompt_repo = PromptRepository(db)
        self.version_repo = PromptVersionRepository(db)
    
    async def get_default_config(self, provider: str) -> Dict[str, Any]:
        """Get the default configuration for a provider.
        
        Args:
            provider: Provider name (e.g., 'ollama', 'groq')
            
        Returns:
            Default configuration dictionary
        """
        return self.DEFAULT_CONFIGS.get(provider.lower, {}).copy()
    
    async def validate_provider_config(
        self,
        provider: str,
        config: Dict[str, Any],
    ) -> bool:
        """Validate a provider configuration.
        
        Args:
            provider: Provider name
            config: Configuration to validate
            
        Returns:
            True if valid
            
        Raises:
            ValidationError: If configuration is invalid
        """
        # Check if provider is supported
        if provider.lower() not in self.DEFAULT_CONFIGS:
            raise ValidationError(f"Unsupported provider: {provider}")
        
        # Validate temperature
        if "temperature" in config:
            temp = config["temperature"]
            if not isinstance(temp, (int, float)) or temp < 0 or temp > 2:
                raise ValidationError("Temperature must be between 0 and 2")
        
        # Validate max_tokens
        if "max_tokens" in config:
            max_tokens = config["max_tokens"]
            if max_tokens is not None and (not isinstance(max_tokens, int) or max_tokens < 1):
                raise ValidationError("max_tokens must be a positive integer or null")
        
        # Validate top_p
        if "top_p" in config:
            top_p = config["top_p"]
            if top_p is not None and (not isinstance(top_p, (int, float)) or top_p < 0 or top_p > 1):
                raise ValidationError("top_p must be between 0 and 1")
        
        # Validate frequency_penalty
        if "frequency_penalty" in config:
            freq_penalty = config["frequency_penalty"]
            if freq_penalty is not None and (not isinstance(freq_penalty, (int, float)) or freq_penalty < -2 or freq_penalty > 2):
                raise ValidationError("frequency_penalty must be between -2 and 2")
        
        # Validate presence_penalty
        if "presence_penalty" in config:
            pres_penalty = config["presence_penalty"]
            if pres_penalty is not None and (not isinstance(pres_penalty, (int, float)) or pres_penalty < -2 or pres_penalty > 2):
                raise ValidationError("presence_penalty must be between -2 and 2")
        
        return True
    
    async def set_version_provider_config(
        self,
        version_id: str,
        provider: str,
        config: Dict[str, Any],
    ) -> PromptVersion:
        """Set the provider configuration for a specific version.
        
        Args:
            version_id: ID of the version
            provider: Provider name
            config: Provider configuration
            
        Returns:
            Updated version
            
        Raises:
            EntityNotFoundException: If version not found
            ValidationError: If configuration is invalid
        """
        # Validate configuration
        await self.validate_provider_config(provider, config)
        
        # Get version
        version = await self.version_repo.get(version_id)
        if not version:
            raise EntityNotFoundException("Prompt version not found")
        
        # Update provider config
        updated_config = config.copy()
        updated_config["provider"] = provider
        
        version = await self.version_repo.update(
            version,
            obj_in={"provider_config": updated_config},
        )
        await self.db.commit()
        
        await logger.ainfo(
            "Version provider config updated",
            version_id=version_id,
            provider=provider,
        )
        
        return version
    
    async def get_version_provider_config(
        self,
        version_id: str,
    ) -> Dict[str, Any]:
        """Get the provider configuration for a specific version.
        
        Args:
            version_id: ID of the version
            
        Returns:
            Provider configuration dictionary
            
        Raises:
            EntityNotFoundException: If version not found
        """
        version = await self.version_repo.get(version_id)
        if not version:
            raise EntityNotFoundException("Prompt version not found")
        
        return version.provider_config.copy()
    
    async def merge_provider_config(
        self,
        base_config: Dict[str, Any],
        override_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Merge two provider configurations with override taking precedence.
        
        Args:
            base_config: Base configuration
            override_config: Override configuration
            
        Returns:
            Merged configuration
        """
        merged = base_config.copy()
        merged.update(override_config)
        return merged
    
    async def get_effective_config(
        self,
        version_id: str,
        override_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Get the effective configuration for a version with optional overrides.
        
        Args:
            version_id: ID of the version
            override_config: Optional override configuration
            
        Returns:
            Effective configuration
        """
        version = await self.version_repo.get(version_id)
        if not version:
            raise EntityNotFoundException("Prompt version not found")
        
        # Get version's provider config
        version_config = version.provider_config.copy()
        
        # If version has no config, use default
        if not version_config:
            provider = version_config.get("provider", "ollama")
            version_config = await self.get_default_config(provider)
        
        # Apply overrides if provided
        if override_config:
            version_config = await self.merge_provider_config(
                version_config, override_config
            )
        
        return version_config
    
    async def list_supported_providers(self) -> List[str]:
        """List all supported providers.
        
        Returns:
            List of provider names
        """
        return list(self.DEFAULT_CONFIGS.keys())
    
    async def get_provider_schema(self, provider: str) -> Dict[str, Any]:
        """Get the schema for a provider's configuration.
        
        Args:
            provider: Provider name
            
        Returns:
            Schema dictionary with field descriptions
        """
        schemas = {
            "ollama": {
                "temperature": {
                    "type": "float",
                    "min": 0.0,
                    "max": 2.0,
                    "default": 0.7,
                    "description": "Sampling temperature",
                },
                "max_tokens": {
                    "type": "integer",
                    "min": 1,
                    "default": None,
                    "description": "Maximum tokens to generate",
                },
                "top_p": {
                    "type": "float",
                    "min": 0.0,
                    "max": 1.0,
                    "default": None,
                    "description": "Nucleus sampling threshold",
                },
            },
            "groq": {
                "temperature": {
                    "type": "float",
                    "min": 0.0,
                    "max": 2.0,
                    "default": 0.7,
                    "description": "Sampling temperature",
                },
                "max_tokens": {
                    "type": "integer",
                    "min": 1,
                    "default": 1024,
                    "description": "Maximum tokens to generate",
                },
                "top_p": {
                    "type": "float",
                    "min": 0.0,
                    "max": 1.0,
                    "default": 0.9,
                    "description": "Nucleus sampling threshold",
                },
                "frequency_penalty": {
                    "type": "float",
                    "min": -2.0,
                    "max": 2.0,
                    "default": 0.0,
                    "description": "Frequency penalty",
                },
                "presence_penalty": {
                    "type": "float",
                    "min": -2.0,
                    "max": 2.0,
                    "default": 0.0,
                    "description": "Presence penalty",
                },
            },
            "openai": {
                "temperature": {
                    "type": "float",
                    "min": 0.0,
                    "max": 2.0,
                    "default": 0.7,
                    "description": "Sampling temperature",
                },
                "max_tokens": {
                    "type": "integer",
                    "min": 1,
                    "default": 1024,
                    "description": "Maximum tokens to generate",
                },
                "top_p": {
                    "type": "float",
                    "min": 0.0,
                    "max": 1.0,
                    "default": 0.9,
                    "description": "Nucleus sampling threshold",
                },
                "frequency_penalty": {
                    "type": "float",
                    "min": -2.0,
                    "max": 2.0,
                    "default": 0.0,
                    "description": "Frequency penalty",
                },
                "presence_penalty": {
                    "type": "float",
                    "min": -2.0,
                    "max": 2.0,
                    "default": 0.0,
                    "description": "Presence penalty",
                },
            },
        }
        
        return schemas.get(provider.lower(), {})
