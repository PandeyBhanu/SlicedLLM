from typing import Any, Dict, Optional
import structlog

from app.evaluation.rubrics.base import BaseRubric, RubricResult

logger = structlog.get_logger(__name__)


class GroundingCheck(BaseRubric):
    """Evaluates whether the generated text is properly grounded in provided context.
    
    This rubric checks for:
    - Adherence to provided context/documents
    - Absence of hallucinations (facts not in context)
    - Proper citation of sources
    - Attribution of information
    - Avoidance of unsupported claims
    """

    async def evaluate(
        self,
        generated_text: str,
        expected_behavior: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> RubricResult:
        """Evaluate grounding compliance of generated text."""
        
        issues = []
        confidence = 1.0
        text_lower = generated_text.lower()
        
        # Get source context if available
        source_context = context.get("source_context", "") if context else ""
        source_context_lower = source_context.lower()
        
        # Check for required source references
        required_sources = expected_behavior.get("required_sources", [])
        for source in required_sources:
            if source.lower() not in text_lower:
                issues.append(f"Missing required source reference: {source}")
                confidence -= 0.3

        # Check for forbidden claims (facts not in context)
        forbidden_claims = expected_behavior.get("forbidden_claims", [])
        for claim in forbidden_claims:
            if claim.lower() in text_lower:
                issues.append(f"Contains forbidden/unsupported claim: {claim}")
                confidence -= 0.5

        # Check for citation format if required
        require_citations = expected_behavior.get("require_citations", False)
        if require_citations:
            # Simple check for citation patterns like [1], (Source A), etc.
            import re
            citation_patterns = [
                r'\[\d+\]',  # [1], [2], etc.
                r'\([^)]+source[^)]*\)',  # (Source A), (from source), etc.
                r'\([^)]+\d{4}\)',  # (Author, 2024) style
            ]
            
            has_citation = any(re.search(pattern, text_lower) for pattern in citation_patterns)
            if not has_citation and len(generated_text) > 50:
                issues.append("Lacks proper citations when citations are required")
                confidence -= 0.4

        # Check for grounding in provided context
        if source_context:
            # Extract key phrases from context and check if they're referenced
            context_words = set(source_context_lower.split())
            generated_words = set(text_lower.split())
            
            # Calculate overlap
            overlap = context_words & generated_words
            overlap_ratio = len(overlap) / len(generated_words) if generated_words else 0
            
            min_grounding_ratio = expected_behavior.get("min_grounding_ratio", 0.3)
            if overlap_ratio < min_grounding_ratio:
                issues.append(
                    f"Low grounding in source context: {overlap_ratio:.2f} < {min_grounding_ratio}"
                )
                confidence -= 0.3

        # Check for hallucination indicators
        hallucination_indicators = [
            "i believe", "i think", "probably", "maybe", "might be",
            "could be", "possibly", "i'm not sure but"
        ]
        
        require_certainty = expected_behavior.get("require_certainty", False)
        if require_certainty:
            for indicator in hallucination_indicators:
                if indicator in text_lower:
                    issues.append(f"Contains uncertainty indicator (hallucination risk): {indicator}")
                    confidence -= 0.2

        # Check for speculative language when not allowed
        allow_speculation = expected_behavior.get("allow_speculation", True)
        if not allow_speculation:
            speculative_words = ["might", "could", "perhaps", "possibly", "maybe"]
            for word in speculative_words:
                if word in text_lower:
                    issues.append(f"Contains speculative language when not allowed: {word}")
                    confidence -= 0.25

        passed = len(issues) == 0
        confidence = max(0.0, min(1.0, confidence))
        
        reasoning = "Grounding check passed" if passed else f"Grounding issues: {'; '.join(issues[:3])}"
        
        return RubricResult(
            passed=passed,
            confidence_score=confidence,
            reasoning=reasoning,
            metadata={
                "issues": issues,
                "has_source_context": bool(source_context),
                "require_citations": require_citations,
            },
        )

    def get_description(self) -> str:
        return "Evaluates whether generated text is properly grounded in provided context and avoids hallucinations"
