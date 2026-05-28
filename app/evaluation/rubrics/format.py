import re
from typing import Any, Dict, Optional
import structlog

from app.evaluation.rubrics.base import BaseRubric, RubricResult

logger = structlog.get_logger(__name__)


class FormatCheck(BaseRubric):
    """Evaluates whether the generated text matches expected format requirements.
    
    This rubric checks for:
    - JSON format validation
    - Length constraints (min/max characters)
    - Required patterns/regex
    - Presence of specific structural elements
    """

    async def evaluate(
        self,
        generated_text: str,
        expected_behavior: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> RubricResult:
        """Evaluate format compliance of generated text."""
        
        issues = []
        confidence = 1.0
        
        # Check if JSON format is required
        if expected_behavior.get("format") == "json":
            try:
                import json
                json.loads(generated_text)
            except json.JSONDecodeError as e:
                issues.append(f"Invalid JSON format: {str(e)}")
                confidence -= 0.5

        # Check length constraints
        min_length = expected_behavior.get("min_length")
        max_length = expected_behavior.get("max_length")
        
        if min_length and len(generated_text) < min_length:
            issues.append(f"Text too short: {len(generated_text)} < {min_length}")
            confidence -= 0.3
        
        if max_length and len(generated_text) > max_length:
            issues.append(f"Text too long: {len(generated_text)} > {max_length}")
            confidence -= 0.3

        # Check for required patterns
        required_patterns = expected_behavior.get("required_patterns", [])
        for pattern in required_patterns:
            if not re.search(pattern, generated_text, re.IGNORECASE):
                issues.append(f"Missing required pattern: {pattern}")
                confidence -= 0.2

        # Check for forbidden patterns
        forbidden_patterns = expected_behavior.get("forbidden_patterns", [])
        for pattern in forbidden_patterns:
            if re.search(pattern, generated_text, re.IGNORECASE):
                issues.append(f"Contains forbidden pattern: {pattern}")
                confidence -= 0.4

        # Check for required structural elements
        required_elements = expected_behavior.get("required_elements", [])
        for element in required_elements:
            if element not in generated_text:
                issues.append(f"Missing required element: {element}")
                confidence -= 0.2

        passed = len(issues) == 0
        confidence = max(0.0, min(1.0, confidence))
        
        reasoning = "Format check passed" if passed else f"Format issues: {'; '.join(issues)}"
        
        return RubricResult(
            passed=passed,
            confidence_score=confidence,
            reasoning=reasoning,
            metadata={"issues": issues, "text_length": len(generated_text)},
        )

    def get_description(self) -> str:
        return "Evaluates whether generated text matches required format specifications (JSON, length, patterns, structure)"
