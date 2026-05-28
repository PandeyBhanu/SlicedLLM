from typing import Any, Dict, List, Optional
import structlog

from app.evaluation.engine import EvaluationEngine
from app.evaluation.rubrics import BaseRubric, RubricResult
from app.providers.base import BaseLLMProvider
from app.providers.models import GenerationParams

logger = structlog.get_logger(__name__)


class JudgeEvaluationPipeline:
    """Pipeline for judge-based A/B comparison of prompt versions.
    
    This pipeline uses an LLM as a judge to evaluate which version performs better
    on specific criteria. It provides:
    - Structured judge prompts
    - Consistent evaluation criteria
    - Detailed reasoning from the judge
    - Confidence scoring
    """

    def __init__(self, judge_provider: BaseLLMProvider, evaluation_engine: EvaluationEngine):
        self.judge_provider = judge_provider
        self.evaluation_engine = evaluation_engine

    async def evaluate_with_judge(
        self,
        prompt_a: str,
        prompt_b: str,
        test_case: Dict[str, Any],
        evaluation_criteria: List[str],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Use an LLM judge to compare two prompt versions on a single test case.
        
        Args:
            prompt_a: First prompt version
            prompt_b: Second prompt version
            test_case: Test case with input and expected behavior
            evaluation_criteria: List of criteria to evaluate against
            system_prompt: Optional system prompt for the judge
            
        Returns:
            Dict containing judge's decision, reasoning, and confidence
        """
        # Build judge prompt
        judge_prompt = self._build_judge_prompt(
            prompt_a=prompt_a,
            prompt_b=prompt_b,
            test_case=test_case,
            evaluation_criteria=evaluation_criteria,
        )
        
        # Default judge system prompt
        if system_prompt is None:
            system_prompt = self._get_default_judge_system_prompt()
        
        # Get judge's decision
        judge_params = GenerationParams(temperature=0.3, max_tokens=500)
        judge_response = await self.judge_provider.generate_with_retry(
            prompt=judge_prompt,
            system_prompt=system_prompt,
            params=judge_params,
        )
        
        # Parse judge's response
        decision = self._parse_judge_response(judge_response.content)
        
        await logger.adebug(
            "Judge evaluation completed",
            winner=decision.get("winner"),
            confidence=decision.get("confidence"),
        )
        
        return {
            "judge_response": judge_response.content,
            "winner": decision.get("winner"),
            "confidence": decision.get("confidence", 0.5),
            "reasoning": decision.get("reasoning", ""),
            "criteria_scores": decision.get("criteria_scores", {}),
            "raw_judge_output": judge_response.model_dump(),
        }

    async def evaluate_batch_with_judge(
        self,
        prompt_a: str,
        prompt_b: str,
        test_cases: List[Dict[str, Any]],
        evaluation_criteria: List[str],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Evaluate a batch of test cases using the judge.
        
        Args:
            prompt_a: First prompt version
            prompt_b: Second prompt version
            test_cases: List of test cases
            evaluation_criteria: List of criteria to evaluate against
            system_prompt: Optional system prompt for the judge
            
        Returns:
            Dict containing individual judge decisions and aggregate statistics
        """
        await logger.ainfo(
            "Starting judge-based batch evaluation",
            test_cases_count=len(test_cases),
            criteria_count=len(evaluation_criteria),
        )
        
        # Evaluate each test case with the judge
        judge_decisions = []
        for i, test_case in enumerate(test_cases):
            decision = await self.evaluate_with_judge(
                prompt_a=prompt_a,
                prompt_b=prompt_b,
                test_case=test_case,
                evaluation_criteria=evaluation_criteria,
                system_prompt=system_prompt,
            )
            decision["case_index"] = i
            judge_decisions.append(decision)
        
        # Calculate aggregate statistics
        stats = self._calculate_judge_statistics(judge_decisions)
        
        await logger.ainfo(
            "Judge batch evaluation completed",
            stats=stats,
        )
        
        return {
            "decisions": judge_decisions,
            "statistics": stats,
        }

    async def hybrid_evaluation(
        self,
        provider_a: BaseLLMProvider,
        provider_b: BaseLLMProvider,
        prompt_a: str,
        prompt_b: str,
        test_cases: List[Dict[str, Any]],
        rubrics: List[BaseRubric],
        evaluation_criteria: List[str],
        use_judge: bool = True,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Perform hybrid evaluation combining automated rubrics and judge decisions.
        
        This approach provides:
        - Fast, consistent automated rubric evaluation
        - Nuanced judge evaluation for complex criteria
        - Combined scoring and decision making
        
        Args:
            provider_a: Provider for version A
            provider_b: Provider for version B
            prompt_a: Template for version A
            prompt_b: Template for version B
            test_cases: List of test cases
            rubrics: List of automated rubrics
            evaluation_criteria: List of criteria for judge evaluation
            use_judge: Whether to use judge evaluation
            system_prompt: Optional system prompt for the judge
            
        Returns:
            Dict containing both rubric and judge results with combined analysis
        """
        # Run automated rubric evaluation
        rubric_results = await self.evaluation_engine.evaluate_ab_comparison(
            provider_a=provider_a,
            provider_b=provider_b,
            prompt_template_a=prompt_a,
            prompt_template_b=prompt_b,
            test_cases=test_cases,
            rubrics=rubrics,
        )
        
        judge_results = None
        if use_judge:
            # Run judge evaluation
            judge_results = await self.evaluate_batch_with_judge(
                prompt_a=prompt_a,
                prompt_b=prompt_b,
                test_cases=test_cases,
                evaluation_criteria=evaluation_criteria,
                system_prompt=system_prompt,
            )
        
        # Combine results
        combined_analysis = self._combine_results(
            rubric_results=rubric_results,
            judge_results=judge_results,
        )
        
        return {
            "rubric_evaluation": rubric_results,
            "judge_evaluation": judge_results,
            "combined_analysis": combined_analysis,
        }

    def _build_judge_prompt(
        self,
        prompt_a: str,
        prompt_b: str,
        test_case: Dict[str, Any],
        evaluation_criteria: List[str],
    ) -> str:
        """Build a structured prompt for the LLM judge."""
        criteria_text = "\n".join(f"- {criterion}" for criterion in evaluation_criteria)
        
        prompt = f"""You are an impartial judge evaluating two different prompt versions.

**Test Case Input:**
{test_case.get('input_variables', {}).get('input', 'N/A')}

**Expected Behavior:**
{test_case.get('expected_behavior', {})}

**Evaluation Criteria:**
{criteria_text}

**Prompt Version A:**
{prompt_a}

**Prompt Version B:**
{prompt_b}

Please evaluate both prompts based on the criteria above and provide:
1. Which version is better (A, B, or TIE)
2. Your confidence in this decision (0.0 to 1.0)
3. Detailed reasoning for your decision
4. Score each criterion individually (0.0 to 1.0)

Format your response as:
Winner: [A/B/TIE]
Confidence: [0.0-1.0]
Reasoning: [your detailed reasoning]
Criteria Scores: [JSON object with criterion names as keys and scores as values]"""
        
        return prompt

    def _get_default_judge_system_prompt(self) -> str:
        """Get the default system prompt for the judge."""
        return """You are an expert evaluator of AI prompts. Your role is to impartially compare two prompt versions based on specified criteria. 

Be objective, thorough, and provide clear reasoning for your decisions. Consider factors such as:
- Clarity and specificity
- Likelihood of producing desired outputs
- Potential for misinterpretation
- Efficiency and conciseness
- Appropriateness for the intended use case

Always provide honest assessments even when the decision is difficult."""

    def _parse_judge_response(self, response: str) -> Dict[str, Any]:
        """Parse the judge's response into structured data."""
        import re
        import json
        
        result = {
            "winner": "TIE",
            "confidence": 0.5,
            "reasoning": "",
            "criteria_scores": {},
        }
        
        # Extract winner
        winner_match = re.search(r"Winner:\s*(A|B|TIE)", response, re.IGNORECASE)
        if winner_match:
            result["winner"] = winner_match.group(1).upper()
        
        # Extract confidence
        confidence_match = re.search(r"Confidence:\s*([0-9.]+)", response, re.IGNORECASE)
        if confidence_match:
            try:
                result["confidence"] = float(confidence_match.group(1))
            except ValueError:
                pass
        
        # Extract reasoning
        reasoning_match = re.search(r"Reasoning:\s*(.+?)(?=Criteria Scores:|$)", response, re.DOTALL | re.IGNORECASE)
        if reasoning_match:
            result["reasoning"] = reasoning_match.group(1).strip()
        
        # Extract criteria scores
        criteria_match = re.search(r"Criteria Scores:\s*(\{.+?\})", response, re.DOTALL | re.IGNORECASE)
        if criteria_match:
            try:
                result["criteria_scores"] = json.loads(criteria_match.group(1))
            except json.JSONDecodeError:
                pass
        
        return result

    def _calculate_judge_statistics(self, decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate aggregate statistics from judge decisions."""
        total = len(decisions)
        wins_a = sum(1 for d in decisions if d.get("winner") == "A")
        wins_b = sum(1 for d in decisions if d.get("winner") == "B")
        ties = sum(1 for d in decisions if d.get("winner") == "TIE")
        
        avg_confidence = sum(d.get("confidence", 0.5) for d in decisions) / total if total > 0 else 0.5
        
        return {
            "total_evaluations": total,
            "wins_a": wins_a,
            "wins_b": wins_b,
            "ties": ties,
            "win_rate_a": wins_a / total if total > 0 else 0,
            "win_rate_b": wins_b / total if total > 0 else 0,
            "average_confidence": avg_confidence,
        }

    def _combine_results(
        self,
        rubric_results: Dict[str, Any],
        judge_results: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Combine rubric and judge results into a unified analysis."""
        combined = {
            "rubric_winner": rubric_results.get("statistics", {}).get("win_rate_a", 0) > rubric_results.get("statistics", {}).get("win_rate_b", 0),
            "judge_winner": None,
            "final_winner": None,
            "agreement": False,
        }
        
        if judge_results:
            judge_stats = judge_results.get("statistics", {})
            combined["judge_winner"] = judge_stats.get("win_rate_a", 0) > judge_stats.get("win_rate_b", 0)
            
            # Check if rubric and judge agree
            combined["agreement"] = combined["rubric_winner"] == combined["judge_winner"]
            
            # Determine final winner (judge has tie-breaker authority)
            if combined["agreement"]:
                combined["final_winner"] = "A" if combined["rubric_winner"] else "B"
            else:
                # In case of disagreement, prefer judge's decision
                combined["final_winner"] = "A" if combined["judge_winner"] else "B"
                combined["disagreement_reason"] = "Rubric and judge evaluations disagreed; judge decision preferred"
        else:
            combined["final_winner"] = "A" if combined["rubric_winner"] else "B"
        
        return combined
