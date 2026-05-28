import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundException, ValidationError
from app.core.config import settings
from app.evaluation.engine import EvaluationEngine
from app.evaluation.reporting import EvaluationReportGenerator
from app.evaluation.rubrics import ContentCheck, FormatCheck, GroundingCheck, ToneCheck
from app.models.evaluation import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)
from app.providers import GenerationParams, ProviderConfig, global_provider_factory
from app.repositories.evaluation import (
    EvaluationCaseRepository,
    EvaluationDatasetRepository,
    EvaluationResultRepository,
    EvaluationRunRepository,
)
from app.repositories.prompt import PromptVersionRepository
from app.schemas.evaluation import (
    EvaluationCaseCreate,
    EvaluationDatasetCreate,
    EvaluationRunCreate,
)

logger = structlog.get_logger(__name__)


class EvaluationService:
    """Orchestrates datasets, cases, and async parallel evaluation runs."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.dataset_repo = EvaluationDatasetRepository(db)
        self.case_repo = EvaluationCaseRepository(db)
        self.run_repo = EvaluationRunRepository(db)
        self.result_repo = EvaluationResultRepository(db)
        self.version_repo = PromptVersionRepository(db)
        self.evaluation_engine = EvaluationEngine(
            max_concurrent_evaluations=settings.EVALUATION_MAX_CONCURRENT,
            default_timeout=settings.EVALUATION_DEFAULT_TIMEOUT,
        )
        self.provider_factory = global_provider_factory
        self.report_generator = EvaluationReportGenerator()

    async def create_dataset(self, schema: EvaluationDatasetCreate) -> EvaluationDataset:
        """Create a collection database container for test cases."""
        existing = await self.dataset_repo.get_by_name(schema.name)
        if existing:
            raise ValidationError(f"Evaluation dataset with name '{schema.name}' already exists.")
        
        dataset = await self.dataset_repo.create(obj_in=schema.model_dump())
        await self.db.commit()
        await logger.ainfo("Evaluation dataset created", id=dataset.id, name=dataset.name)
        return dataset

    async def add_case_to_dataset(
        self, dataset_id: uuid.UUID, schema: EvaluationCaseCreate
    ) -> EvaluationCase:
        """Add a test case to an evaluation dataset."""
        dataset = await self.dataset_repo.get(dataset_id)
        if not dataset:
            raise EntityNotFoundException("Target evaluation dataset not found.")

        case_data = schema.model_dump()
        case_data["dataset_id"] = dataset_id
        
        case = await self.case_repo.create(obj_in=case_data)
        await self.db.commit()
        await logger.ainfo("Test case added to dataset", dataset_id=dataset_id, case_id=case.id)
        return case

    async def get_dataset(self, id: uuid.UUID) -> EvaluationDataset:
        """Fetch a dataset with pre-loaded test cases."""
        dataset = await self.dataset_repo.get_with_cases(id)
        if not dataset:
            raise EntityNotFoundException("Evaluation dataset not found.")
        return dataset

    async def list_datasets(self, skip: int = 0, limit: int = 100) -> List[EvaluationDataset]:
        """List all datasets."""
        return await self.dataset_repo.get_multi(skip=skip, limit=limit)

    async def execute_evaluation_run(self, schema: EvaluationRunCreate) -> EvaluationRun:
        """Orchestrate and execute evaluation cases concurrently.
        
        Runs a parallel suite of executions comparing prompt version A (and optionally B).
        Updates run states in transactional bounds.
        """
        dataset = await self.dataset_repo.get_with_cases(schema.dataset_id)
        if not dataset:
            raise EntityNotFoundException("Evaluation dataset not found.")
        if not dataset.cases:
            raise ValidationError("Evaluation dataset must have at least one test case to run.")

        version_a = await self.version_repo.get(schema.prompt_version_a_id)
        if not version_a:
            raise EntityNotFoundException("Prompt version A not found.")

        version_b = None
        if schema.prompt_version_b_id:
            version_b = await self.version_repo.get(schema.prompt_version_b_id)
            if not version_b:
                raise EntityNotFoundException("Prompt version B not found.")

        # Create evaluation run record
        run_data = {
            "prompt_version_a_id": schema.prompt_version_a_id,
            "prompt_version_b_id": schema.prompt_version_b_id,
            "provider": schema.provider,
            "model": schema.model,
            "status": "RUNNING",
            "started_at": datetime.now(),
        }
        
        run = await self.run_repo.create(obj_in=run_data)
        await self.db.commit()
        await logger.ainfo("Starting evaluation run", run_id=run.id, cases_count=len(dataset.cases))

        # Launch concurrency task execution
        asyncio.create_task(
            self._background_evaluator_task(run.id, dataset.cases, version_a, version_b, schema)
        )

        return run

    async def get_evaluation_run(self, run_id: uuid.UUID) -> EvaluationRun:
        """Fetch evaluation run metrics and structured result cases."""
        run = await self.run_repo.get_run_with_results(run_id)
        if not run:
            raise EntityNotFoundException("Evaluation run not found.")
        return run

    async def generate_evaluation_report(self, run_id: uuid.UUID) -> Dict[str, Any]:
        """Generate a structured evaluation report for a completed run."""
        run = await self.run_repo.get_run_with_results(run_id)
        if not run:
            raise EntityNotFoundException("Evaluation run not found.")
        
        if run.status != "COMPLETED":
            raise ValidationError("Can only generate reports for completed evaluation runs.")
        
        # Get version information
        version_a = await self.version_repo.get(run.prompt_version_a_id)
        version_b = await self.version_repo.get(run.prompt_version_b_id) if run.prompt_version_b_id else None
        
        # Prepare results for report generation
        results_a = []
        results_b = []
        
        for result in run.results:
            # Convert database result to engine result format
            result_dict = {
                "success": True,
                "overall_score": result.confidence_score,
                "latency_ms": result.latency_ms,
                "estimated_cost": result.estimated_cost,
                "token_usage": result.token_usage,
                "passed": result.confidence_score >= 0.5,
            }
            
            if result.winner == "A" or result.winner is None:
                results_a.append(result_dict)
            if result.winner == "B" or result.winner is None:
                results_b.append(result_dict)
        
        # Generate comparison report
        report = self.report_generator.generate_comparison_report(
            results_a=results_a,
            results_b=results_b if version_b else None,
            version_a_id=str(run.prompt_version_a_id),
            version_a_label=version_a.semantic_version if version_a else "unknown",
            version_b_id=str(run.prompt_version_b_id) if version_b else None,
            version_b_label=version_b.semantic_version if version_b else None,
            evaluation_run_id=str(run_id),
        )
        
        await logger.ainfo("Evaluation report generated", run_id=run_id, report_id=report.report_id)
        
        return report.model_dump()

    async def get_evaluation_history(
        self,
        prompt_id: Optional[uuid.UUID] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get evaluation history with aggregated statistics."""
        # This would typically use a more complex query with joins
        # For now, we'll get all runs and filter/aggregate in memory
        runs = await self.run_repo.get_multi(skip=skip, limit=limit)
        
        history = []
        for run in runs:
            # Filter by prompt if specified
            if prompt_id:
                version_a = await self.version_repo.get(run.prompt_version_a_id)
                if not version_a or version_a.prompt_id != prompt_id:
                    continue
            
            # Calculate aggregate statistics
            total_cases = len(run.results)
            successful_cases = sum(1 for r in run.results if r.confidence_score > 0)
            passed_cases = sum(1 for r in run.results if r.confidence_score >= 0.5)
            
            avg_latency = (
                sum(r.latency_ms for r in run.results) / total_cases
                if total_cases > 0 else 0
            )
            
            total_cost = sum(r.estimated_cost for r in run.results)
            
            history.append({
                "run_id": run.id,
                "status": run.status,
                "provider": run.provider,
                "model": run.model,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
                "total_cases": total_cases,
                "successful_cases": successful_cases,
                "passed_cases": passed_cases,
                "average_latency_ms": avg_latency,
                "total_cost": total_cost,
            })
        
        return history

    async def _background_evaluator_task(
        self,
        run_id: uuid.UUID,
        cases: List[EvaluationCase],
        version_a: Any,
        version_b: Optional[Any],
        schema: EvaluationRunCreate,
    ) -> None:
        """Asynchronous execution worker using new provider abstraction and evaluation engine."""
        try:
            # Create provider instance
            provider_config = ProviderConfig(
                base_url=self._get_provider_base_url(schema.provider),
                api_key=self._get_provider_api_key(schema.provider),
                timeout=120.0,
                max_retries=3,
                max_concurrent_requests=10,
            )
            
            provider = self.provider_factory.create_provider(
                provider_name=schema.provider,
                config=provider_config,
                model=schema.model,
            )
            
            # Set up rubrics for evaluation
            rubrics = [
                FormatCheck(),
                ContentCheck(),
                ToneCheck(),
                GroundingCheck(),
            ]
            
            # Set up generation parameters from version config
            generation_params = GenerationParams(
                temperature=version_a.provider_config.get("temperature", 0.7),
                max_tokens=version_a.provider_config.get("max_tokens"),
                top_p=version_a.provider_config.get("top_p"),
            )
            
            # Prepare test cases for evaluation engine
            test_cases = []
            for case in cases:
                test_cases.append({
                    "input_variables": {"input": case.input_text},
                    "expected_behavior": case.expected_behavior,
                })
            
            # Run evaluation using the evaluation engine
            if version_b:
                # A/B comparison
                comparison_results = await self.evaluation_engine.evaluate_ab_comparison(
                    provider_a=provider,
                    provider_b=provider,  # Same provider, different templates
                    prompt_template_a=version_a.template,
                    prompt_template_b=version_b.template,
                    test_cases=test_cases,
                    system_prompt=None,
                    generation_params=generation_params,
                    rubrics=rubrics,
                    context=None,
                )
                
                # Process comparison results into database records
                results = self._process_comparison_results(
                    comparison_results, run_id, cases
                )
            else:
                # Single version evaluation
                batch_results = await self.evaluation_engine.evaluate_batch(
                    provider=provider,
                    prompt_template=version_a.template,
                    test_cases=test_cases,
                    system_prompt=None,
                    generation_params=generation_params,
                    rubrics=rubrics,
                    context=None,
                )
                
                # Process batch results into database records
                results = self._process_batch_results(batch_results, run_id, cases)

            # Close provider connection
            await provider.close()

            # Save results to database
            async with self.db.begin():
                run = await self.run_repo.get(run_id)
                if not run:
                    return

                success_count = 0
                for result in results:
                    if result:
                        self.db.add(result)
                        success_count += 1

                run.status = "COMPLETED" if success_count > 0 else "FAILED"
                run.completed_at = datetime.now()
                self.db.add(run)

            await self.db.commit()
            await logger.ainfo(
                "Evaluation run finished processing",
                run_id=run_id,
                status=run.status,
                successful_cases=success_count,
            )

        except Exception as e:
            await logger.aexception("Fatal error in evaluation worker task", run_id=run_id, error=str(e))
            try:
                async with self.db.begin():
                    run = await self.run_repo.get(run_id)
                    if run:
                        run.status = "FAILED"
                        run.completed_at = datetime.now()
                        self.db.add(run)
                await self.db.commit()
            except Exception as nested_err:
                await logger.aerror("Failed to mark evaluation run as failed", error=str(nested_err))

    def _get_provider_base_url(self, provider_name: str) -> str:
        """Get the base URL for a provider from settings."""
        provider_urls = {
            "ollama": settings.OLLAMA_BASE_URL,
            "groq": settings.GROQ_BASE_URL,
        }
        return provider_urls.get(provider_name.lower(), "http://localhost:11434")

    def _get_provider_api_key(self, provider_name: str) -> Optional[str]:
        """Get the API key for a provider from settings."""
        provider_keys = {
            "ollama": None,  # Ollama doesn't require API keys
            "groq": settings.GROQ_API_KEY,
        }
        return provider_keys.get(provider_name.lower())

    def _process_batch_results(
        self,
        batch_results: List[Dict[str, Any]],
        run_id: uuid.UUID,
        cases: List[EvaluationCase],
    ) -> List[EvaluationResult]:
        """Process batch evaluation results into database records."""
        results = []
        for i, (result, case) in enumerate(zip(batch_results, cases)):
            if not result.get("success"):
                continue
            
            evaluation_result = EvaluationResult(
                evaluation_run_id=run_id,
                evaluation_case_id=case.id,
                winner=None,  # Single evaluation has no winner
                confidence_score=result.get("overall_score", 0.0),
                reasoning=f"Overall score: {result.get('overall_score', 0.0):.2f}",
                latency_ms=result.get("latency_ms", 0.0),
                token_usage=result.get("token_usage", {}),
                estimated_cost=result.get("estimated_cost", 0.0),
            )
            results.append(evaluation_result)
        
        return results

    def _process_comparison_results(
        self,
        comparison_results: Dict[str, Any],
        run_id: uuid.UUID,
        cases: List[EvaluationCase],
    ) -> List[EvaluationResult]:
        """Process A/B comparison results into database records."""
        results = []
        comparisons = comparison_results.get("comparisons", [])
        
        for comparison in comparisons:
            case_index = comparison.get("case_index", 0)
            if case_index >= len(cases):
                continue
            
            case = cases[case_index]
            result_a = comparison.get("result_a", {})
            result_b = comparison.get("result_b", {})
            
            # Only create result if at least one version succeeded
            if not result_a.get("success") and not result_b.get("success"):
                continue
            
            # Calculate combined metrics
            latency_a = result_a.get("latency_ms", 0) if result_a.get("success") else 0
            latency_b = result_b.get("latency_ms", 0) if result_b.get("success") else 0
            avg_latency = (latency_a + latency_b) / 2 if (latency_a + latency_b) > 0 else 0
            
            cost_a = result_a.get("estimated_cost", 0) if result_a.get("success") else 0
            cost_b = result_b.get("estimated_cost", 0) if result_b.get("success") else 0
            total_cost = cost_a + cost_b
            
            token_usage = {
                "version_a": result_a.get("token_usage") if result_a.get("success") else None,
                "version_b": result_b.get("token_usage") if result_b.get("success") else None,
            }
            
            evaluation_result = EvaluationResult(
                evaluation_run_id=run_id,
                evaluation_case_id=case.id,
                winner=comparison.get("winner"),
                confidence_score=0.85,  # Default confidence for A/B comparisons
                reasoning=f"Winner: {comparison.get('winner')}, Score difference: {comparison.get('score_difference', 0):.2f}",
                latency_ms=avg_latency,
                token_usage=token_usage,
                estimated_cost=total_cost,
            )
            results.append(evaluation_result)
        
        return results
