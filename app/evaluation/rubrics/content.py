from typing import Any, Dict, Optional
import structlog

from app.evaluation.rubrics.base import BaseRubric, RubricResult

logger = structlog.get_logger(__name__)


class ContentCheck(BaseRubric):
    """Evaluates whether the generated text contains required content elements.
    
    This rubric checks for:
    - Required keywords/phrases
    - Excluded keywords/phrases
    - Factual accuracy (basic keyword matching)
    - Completeness of information
    """

    async def evaluate(
        self,
        generated_text: str,
        expected_behavior: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> RubricResult:
        """Evaluate content compliance of generated text."""
        
        issues = []
        matches = []
        confidence = 1.0
        text_lower = generated_text.lower()
        
        # Check for required keywords
        required_keywords = expected_behavior.get("keywords", [])
        for keyword in required_keywords:
            if keyword.lower() in text_lower:
                matches.append(keyword)
            else:
                issues.append(f"Missing required keyword: {keyword}")
                confidence -= 0.25

        # Check for excluded keywords
        excluded_keywords = expected_behavior.get("excluded_keywords", [])
        for keyword in excluded_keywords:
            if keyword.lower() in text_lower:
                issues.append(f"Contains excluded keyword: {keyword}")
                confidence -= 0.3

        # Check for required phrases (multi-word)
        required_phrases = expected_behavior.get("required_phrases", [])
        for phrase in required_phrases:
            if phrase.lower() in text_lower:
                matches.append(phrase)
            else:
                issues.append(f"Missing required phrase: {phrase}")
                confidence -= 0.2

        # Check for semantic categories (simple keyword-based)
        required_categories = expected_behavior.get("required_categories", [])
        for category, keywords in required_categories.items():
            category_match = any(kw.lower() in text_lower for kw in keywords)
            if category_match:
                matches.append(f"category:{category}")
            else:
                issues.append(f"Missing content from category: {category}")
                confidence -= 0.15

        # Check minimum information density
        min_info_density = expected_behavior.get("min_info_density", 0)
        if min_info_density > 0:
            # Simple heuristic: unique words / total words
            words = generated_text.split()
            if words:
                unique_words = len(set(word.lower() for word in words))
                density = unique_words / len(words)
                if density < min_info_density:
                    issues.append(f"Low information density: {density:.2f} < {min_info_density}")
                    confidence -= 0.2

        passed = len(issues) == 0
        confidence = max(0.0, min(1.0, confidence))
        
        reasoning = (
            f"Content check passed. Found: {len(matches)} required elements"
            if passed
            else f"Content issues: {'; '.join(issues[:5])}"
        )
        
        return RubricResult(
            passed=passed,
            confidence_score=confidence,
            reasoning=reasoning,
            metadata={
                "issues": issues,
                "matches": matches,
                "total_required": len(required_keywords) + len(required_phrases),
            },
        )

    def get_description(self) -> str:
        return "Evaluates whether generated text contains required content elements (keywords, phrases, categories)"
