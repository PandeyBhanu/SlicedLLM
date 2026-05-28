import asyncio
import time
from typing import Any, Dict, List, Optional
import structlog

from app.evaluation.rubrics import BaseRubric, RubricResult
from app.providers.base import BaseLLMProvider
from app.providers.models import GenerationParams, LLMResponse

logger = structlog.get_logger(__name__)


class EvaluationEngine:
    """Orchestrates async evaluation of prompt versions against datasets.
    
    This engine handles:
    - Concurrent execution with semaphore-based rate limiting
    - Provider-agnostic evaluation through BaseLLMProvider interface
    - Rubric-based evaluation of generated responses
    - Latency, token usage, and cost tracking
    - Graceful error handling and recovery
    """

    def __init__(
        self,
        max_concurrent_evaluations: int = 10,
        default_timeout: float = 120.0,
    ):
        self.max_concurrent_evaluations = max_concurrent_evaluations
        self.default_timeout = default_timeout
        self.semaphore = asyncio.Semaphore(max_concurrent_evaluations)

    async def evaluate_single_case(
        self,
        provider: BaseLLMProvider,
        prompt_template: str,
        input_variables: Dict[str, Any],
        system_prompt: Optional[str] = None,
        generation_params: Optional[GenerationParams] = None,
        rubrics: Optional[List[BaseRubric]] = None,
        expected_behavior: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Evaluate a single test case with the given provider and rubrics.
        
        Args:
            provider: The LLM provider to use
            prompt_template: The prompt template to compile
            input_variables: Variables to substitute into the template
            system_prompt: Optional system prompt
            generation_params: Generation parameters
            rubrics: List of rubrics to evaluate against
            expected_behavior: Expected behavior for rubric evaluation
            context: Additional context for evaluation
            
        Returns:
            Dict containing generation results and rubric evaluations
        """
        async with self.semaphore:
            start_time = time.perf_counter()
            
            try:
                # Compile the prompt template
                compiled_prompt = self._compile_template(prompt_template, input_variables)
                
                # Generate response with timeout
                llm_response = await asyncio.wait_for(
                    provider.generate_with_retry(
                        prompt=compiled_prompt,
                        system_prompt=system_prompt,
                        params=generation_params,
                    ),
                    timeout=self.default_timeout,
                )
                
                generation_time = time.perf_counter() - start_time
                
                # Run rubric evaluations
                rubric_results = []
                if rubrics and expected_behavior:
                    rubric_results = await self._evaluate_rubrics(
                        llm_response.content,
                        expected_behavior,
                        rubrics,
                        context,
                    )
                
                # Calculate overall score
                overall_score = self._calculate_overall_score(rubric_results)
                
                result = {
                    "success": True,
                    "generated_content": llm_response.content,
                    "provider": llm_response.provider,
                    "model": llm_response.model,
                    "latency_ms": llm_response.latency_ms,
                    "generation_time_s": generation_time,
                    "token_usage": llm_response.token_usage.model_dump() if llm_response.token_usage else None,
                    "estimated_cost": llm_response.estimated_cost,
                    "rubric_results": [r.model_dump() for r in rubric_results],
                    "overall_score": overall_score,
                    "passed": overall_score >= 0.5,  # Pass if score >= 50%
                }
                
                await logger.adebug(
                    "Single case evaluation completed",
                    provider=llm_response.provider,
                    model=llm_response.model,
                    latency_ms=llm_response.latency_ms,
                    overall_score=overall_score,
                )
                
                return result
                
            except asyncio.TimeoutError:
                await logger.awarning(
                    "Evaluation case timed out",
                    provider=provider.provider_name,
                    timeout=self.default_timeout,
                )
                return {
                    "success": False,
                    "error": "timeout",
                    "error_message": f"Evaluation timed out after {self.default_timeout}s",
                    "latency_ms": self.default_timeout * 1000,
                }
                
            except Exception as e:
                await logger.aerror(
                    "Evaluation case failed",
                    provider=provider.provider_name,
                    error=str(e),
                )
                return {
                    "success": False,
                    "error": "execution_error",
                    "error_message": str(e),
                    "latency_ms": (time.perf_counter() - start_time) * 1000,
                }

    async def evaluate_batch(
        self,
        provider: BaseLLMProvider,
        prompt_template: str,
        test_cases: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        generation_params: Optional[GenerationParams] = None,
        rubrics: Optional[List[BaseRubric]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Evaluate a batch of test cases concurrently.
        
        Args:
            provider: The LLM provider to use
            prompt_template: The prompt template to compile
            test_cases: List of test cases with input_variables and expected_behavior
            system_prompt: Optional system prompt
            generation_params: Generation parameters
            rubrics: List of rubrics to evaluate against
            context: Additional context for evaluation
            
        Returns:
            List of evaluation results for each test case
        """
        await logger.ainfo(
            "Starting batch evaluation",
            provider=provider.provider_name,
            test_cases_count=len(test_cases),
            max_concurrent=self.max_concurrent_evaluations,
        )
        
        batch_start_time = time.perf_counter()
        
        # Create tasks for all test cases
        tasks = [
            self.evaluate_single_case(
                provider=provider,
                prompt_template=prompt_template,
                input_variables=case.get("input_variables", {}),
                system_prompt=system_prompt,
                generation_params=generation_params,
                rubrics=rubrics,
                expected_behavior=case.get("expected_behavior"),
                context=context,
            )
            for case in test_cases
        ]
        
        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle any exceptions that weren't caught in evaluate_single_case
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                await logger.aerror(
                    "Unhandled exception in batch evaluation",
                    case_index=i,
                    error=str(result),
                )
                processed_results.append({
                    "success": False,
                    "error": "unhandled_exception",
                    "error_message": str(result),
                })
            else:
                processed_results.append(result)
        
        batch_time = time.perf_counter() - batch_start_time
        
        # Calculate batch statistics
        successful = sum(1 for r in processed_results if r.get("success"))
        passed = sum(1 for r in processed_results if r.get("passed"))
        
        await logger.ainfo(
            "Batch evaluation completed",
            provider=provider.provider_name,
            total_cases=len(test_cases),
            successful=successful,
            passed=passed,
            batch_time_s=batch_time,
        )
        
        return processed_results

    async def evaluate_ab_comparison(
        self,
        provider_a: BaseLLMProvider,
        provider_b: BaseLLMProvider,
        prompt_template_a: str,
        prompt_template_b: str,
        test_cases: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        generation_params: Optional[GenerationParams] = None,
        rubrics: Optional[List[BaseRubric]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform A/B comparison evaluation between two prompt versions.
        
        Args:
            provider_a: Provider for version A
            provider_b: Provider for version B
            prompt_template_a: Template for version A
            prompt_template_b: Template for version B
            test_cases: List of test cases
            system_prompt: Optional system prompt
            generation_params: Generation parameters
            rubrics: List of rubrics to evaluate against
            context: Additional context for evaluation
            
        Returns:
            List of comparison results with winner determination
        """
        await logger.ainfo(
            "Starting A/B comparison evaluation",
            provider_a=provider_a.provider_name,
            provider_b=provider_b.provider_name,
            test_cases_count=len(test_cases),
        )
        
        # Evaluate both versions concurrently
        results_a = await self.evaluate_batch(
            provider=provider_a,
            prompt_template=prompt_template_a,
            test_cases=test_cases,
            system_prompt=system_prompt,
            generation_params=generation_params,
            rubrics=rubrics,
            context=context,
        )
        
        results_b = await self.evaluate_batch(
            provider=provider_b,
            prompt_template=prompt_template_b,
            test_cases=test_cases,
            system_prompt=system_prompt,
            generation_params=generation_params,
            rubrics=rubrics,
            context=context,
        )
        
        # Compare results and determine winners
        comparison_results = []
        for i, (result_a, result_b) in enumerate(zip(results_a, results_b)):
            comparison = self._compare_results(result_a, result_b, i)
            comparison_results.append(comparison)
        
        # Calculate aggregate statistics
        stats = self._calculate_comparison_stats(comparison_results)
        
        await logger.ainfo(
            "A/B comparison completed",
            stats=stats,
        )
        
        return {
            "comparisons": comparison_results,
            "statistics": stats,
        }

    def _compile_template(self, template: str, variables: Dict[str, Any]) -> str:
        """Simple template compilation using {{variable}} syntax."""
        import re
        pattern = r"\{\{\s*(\w+)\s*\}\}"
        
        def replace(match):
            var_name = match.group(1)
            return str(variables.get(var_name, f"[{var_name}]"))
        
        return re.sub(pattern, replace, template)

    async def _evaluate_rubrics(
        self,
        generated_text: str,
        expected_behavior: Dict[str, Any],
        rubrics: List[BaseRubric],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RubricResult]:
        """Run all rubrics against the generated text."""
        results = []
        for rubric in rubrics:
            result = await rubric.evaluate_with_logging(
                generated_text=generated_text,
                expected_behavior=expected_behavior,
                context=context,
            )
            results.append(result)
        return results

    def _calculate_overall_score(self, rubric_results: List[RubricResult]) -> float:
        """Calculate overall score from rubric results."""
        if not rubric_results:
            return 1.0  # No rubrics = perfect score by default
        
        # Weighted average based on confidence
        total_weight = 0.0
        weighted_score = 0.0
        
        for result in rubric_results:
            weight = result.confidence_score
            score = 1.0 if result.passed else 0.0
            weighted_score += score * weight
            total_weight += weight
        
        return weighted_score / total_weight if total_weight > 0 else 0.0

    def _compare_results(
        self,
        result_a: Dict[str, Any],
        result_b: Dict[str, Any],
        case_index: int,
    ) -> Dict[str, Any]:
        """Compare two evaluation results and determine a winner."""
        score_a = result_a.get("overall_score", 0.0)
        score_b = result_b.get("overall_score", 0.0)
        
        if abs(score_a - score_b) < 0.05:  # Within 5% = tie
            winner = "TIE"
        elif score_a > score_b:
            winner = "A"
        else:
            winner = "B"
        
        return {
            "case_index": case_index,
            "result_a": result_a,
            "result_b": result_b,
            "winner": winner,
            "score_difference": score_a - score_b,
        }

    def _calculate_comparison_stats(self, comparisons: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate aggregate statistics from A/B comparison."""
        total = len(comparisons)
        wins_a = sum(1 for c in comparisons if c["winner"] == "A")
        wins_b = sum(1 for c in comparisons if c["winner"] == "B")
        ties = sum(1 for c in comparisons if c["winner"] == "TIE")
        
        # Calculate average latencies
        latencies_a = [c["result_a"].get("latency_ms", 0) for c in comparisons if c["result_a"].get("success")]
        latencies_b = [c["result_b"].get("latency_ms", 0) for c in comparisons if c["result_b"].get("success")]
        
        avg_latency_a = sum(latencies_a) / len(latencies_a) if latencies_a else 0
        avg_latency_b = sum(latencies_b) / len(latencies_b) if latencies_b else 0
        
        # Calculate total costs
        total_cost_a = sum(c["result_a"].get("estimated_cost", 0) for c in comparisons if c["result_a"].get("success"))
        total_cost_b = sum(c["result_b"].get("estimated_cost", 0) for c in comparisons if c["result_b"].get("success"))
        
        return {
            "total_comparisons": total,
            "wins_a": wins_a,
            "wins_b": wins_b,
            "ties": ties,
            "win_rate_a": wins_a / total if total > 0 else 0,
            "win_rate_b": wins_b / total if total > 0 else 0,
            "avg_latency_a_ms": avg_latency_a,
            "avg_latency_b_ms": avg_latency_b,
            "total_cost_a": total_cost_a,
            "total_cost_b": total_cost_b,
        }
