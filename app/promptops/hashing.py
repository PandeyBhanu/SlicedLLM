import hashlib
import json
import uuid
from typing import Any


def canonical_json(data: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 characters preserved."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_content_hash(
    *,
    prompt_id: uuid.UUID | str,
    semantic_version: str,
    template: str,
    metadata: dict[str, Any],
    provider_config: dict[str, Any],
) -> str:
    """Hash of everything that defines an immutable prompt version."""
    return sha256_hex(
        canonical_json(
            {
                "prompt_id": str(prompt_id),
                "semantic_version": semantic_version,
                "template": template,
                "metadata": metadata,
                "provider_config": provider_config,
            }
        )
    )
