"""Rubric definitions. A rubric is explicit, versioned data stored in the `rubrics` table."""

from typing import Any

from app.promptops.hashing import canonical_json, sha256_hex

DEFAULT_RUBRIC_NAME = "general-quality"
DEFAULT_RUBRIC_VERSION = 1
SCALE_MIN = 1
SCALE_MAX = 5

DEFAULT_CRITERIA: list[dict[str, Any]] = [
    {
        "name": "correctness",
        "description": (
            "Facts, reasoning and any computed results are accurate and consistent "
            "with the expected behavior."
        ),
        "weight": 2.0,
    },
    {
        "name": "relevance",
        "description": "The response addresses exactly what the input asks and stays on topic.",
        "weight": 1.0,
    },
    {
        "name": "instruction_following",
        "description": (
            "The response obeys the instructions and format requested in the prompt it was given."
        ),
        "weight": 1.0,
    },
    {
        "name": "clarity",
        "description": "The response is clear, well organised and free of unnecessary padding.",
        "weight": 1.0,
    },
]


def rubric_hash(
    name: str, version: int, criteria: list[dict[str, Any]], scale_min: int, scale_max: int
) -> str:
    return sha256_hex(
        canonical_json(
            {
                "name": name,
                "version": version,
                "criteria": criteria,
                "scale_min": scale_min,
                "scale_max": scale_max,
            }
        )
    )


def validate_criteria(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not criteria:
        raise ValueError("A rubric needs at least one criterion")
    seen = set()
    cleaned = []
    for c in criteria:
        name = str(c.get("name", "")).strip()
        if not name or name in seen:
            raise ValueError("Criterion names must be non-empty and unique")
        weight = float(c.get("weight", 1.0))
        if weight <= 0:
            raise ValueError("Criterion weights must be positive")
        seen.add(name)
        cleaned.append(
            {"name": name, "description": str(c.get("description", "")).strip(), "weight": weight}
        )
    return cleaned
