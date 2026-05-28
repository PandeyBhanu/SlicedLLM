from typing import Any, Dict, Optional
import structlog

from app.evaluation.rubrics.base import BaseRubric, RubricResult

logger = structlog.get_logger(__name__)


class ToneCheck(BaseRubric):
    """Evaluates whether the generated text matches the expected tone/style.
    
    This rubric checks for:
    - Professional vs casual language
    - Politeness and courtesy
    - Emotional sentiment
    - Formality level
    - Appropriate language for the context
    """

    # Tone indicators
    PROFESSIONAL_INDICATORS = [
        "please", "thank you", "regarding", "furthermore", "consequently",
        "sincerely", "respectfully", "appreciate", "assistance", "inquiry"
    ]
    
    CASUAL_INDICATORS = [
        "hey", "yo", "sup", "cool", "awesome", "yeah", "nah", "gonna",
        "wanna", "kinda", "sorta", "lol", "haha"
    ]
    
    FORMAL_INDICATORS = [
        "therefore", "however", "moreover", "nevertheless", "subsequently",
        "pursuant", "accordance", "herein", "hereby", "wherein"
    ]
    
    NEGATIVE_INDICATORS = [
        "terrible", "awful", "horrible", "hate", "stupid", "dumb",
        "worst", "sucks", "annoying", "frustrating"
    ]
    
    POSITIVE_INDICATORS = [
        "excellent", "great", "wonderful", "fantastic", "amazing",
        "helpful", "useful", "effective", "successful", "beneficial"
    ]

    async def evaluate(
        self,
        generated_text: str,
        expected_behavior: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> RubricResult:
        """Evaluate tone compliance of generated text."""
        
        issues = []
        confidence = 1.0
        text_lower = generated_text.lower()
        
        # Check required tone
        required_tone = expected_behavior.get("tone", "professional")
        
        if required_tone == "professional":
            professional_count = sum(1 for ind in self.PROFESSIONAL_INDICATORS if ind in text_lower)
            casual_count = sum(1 for ind in self.CASUAL_INDICATORS if ind in text_lower)
            
            if professional_count < 1 and len(generated_text) > 50:
                issues.append("Lacks professional language indicators")
                confidence -= 0.3
            
            if casual_count > 2:
                issues.append(f"Contains too many casual indicators: {casual_count}")
                confidence -= 0.4
        
        elif required_tone == "casual":
            casual_count = sum(1 for ind in self.CASUAL_INDICATORS if ind in text_lower)
            if casual_count < 1 and len(generated_text) > 30:
                issues.append("Lacks casual language indicators")
                confidence -= 0.3
        
        elif required_tone == "formal":
            formal_count = sum(1 for ind in self.FORMAL_INDICATORS if ind in text_lower)
            if formal_count < 1 and len(generated_text) > 50:
                issues.append("Lacks formal language indicators")
                confidence -= 0.3
        
        # Check sentiment requirements
        required_sentiment = expected_behavior.get("sentiment")
        if required_sentiment == "positive":
            positive_count = sum(1 for ind in self.POSITIVE_INDICATORS if ind in text_lower)
            negative_count = sum(1 for ind in self.NEGATIVE_INDICATORS if ind in text_lower)
            
            if negative_count > positive_count:
                issues.append("Contains more negative than positive language")
                confidence -= 0.5
            
            if positive_count < 1 and len(generated_text) > 30:
                issues.append("Lacks positive sentiment indicators")
                confidence -= 0.3
        
        elif required_sentiment == "negative":
            negative_count = sum(1 for ind in self.NEGATIVE_INDICATORS if ind in text_lower)
            if negative_count < 1 and len(generated_text) > 30:
                issues.append("Lacks negative sentiment indicators")
                confidence -= 0.3
        
        elif required_sentiment == "neutral":
            positive_count = sum(1 for ind in self.POSITIVE_INDICATORS if ind in text_lower)
            negative_count = sum(1 for ind in self.NEGATIVE_INDICATORS if ind in text_lower)
            
            if positive_count > 2 or negative_count > 2:
                issues.append("Contains strong sentiment indicators (should be neutral)")
                confidence -= 0.4
        
        # Check for politeness
        require_politeness = expected_behavior.get("require_politeness", True)
        if require_politeness:
            polite_indicators = ["please", "thank", "appreciate", "regards"]
            polite_count = sum(1 for ind in polite_indicators if ind in text_lower)
            
            if polite_count < 1 and len(generated_text) > 40:
                issues.append("Lacks politeness indicators")
                confidence -= 0.2
        
        # Check for offensive language
        offensive_words = expected_behavior.get("forbidden_offensive", [])
        for word in offensive_words:
            if word.lower() in text_lower:
                issues.append(f"Contains offensive language: {word}")
                confidence -= 0.6

        passed = len(issues) == 0
        confidence = max(0.0, min(1.0, confidence))
        
        reasoning = "Tone check passed" if passed else f"Tone issues: {'; '.join(issues[:3])}"
        
        return RubricResult(
            passed=passed,
            confidence_score=confidence,
            reasoning=reasoning,
            metadata={
                "issues": issues,
                "required_tone": required_tone,
                "required_sentiment": required_sentiment,
            },
        )

    def get_description(self) -> str:
        return "Evaluates whether generated text matches the expected tone/style (professional, casual, formal, sentiment)"
