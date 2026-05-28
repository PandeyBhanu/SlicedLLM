from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import structlog

logger = structlog.get_logger(__name__)


class RubricSummary(BaseModel):
    """Summary of rubric evaluation results."""
    rubric_name: str = Field(..., description="Name of the rubric")
    total_evaluations: int = Field(..., description="Total number of evaluations")
    passed_count: int = Field(..., description="Number of evaluations that passed")
    failed_count: int = Field(..., description="Number of evaluations that failed")
    pass_rate: float = Field(..., description="Pass rate (0.0 to 1.0)")
    average_confidence: float = Field(..., description="Average confidence score")
    common_failures: List[str] = Field(default_factory=list, description="Common failure reasons")


class LatencyMetrics(BaseModel):
    """Latency performance metrics."""
    average_ms: float = Field(..., description="Average latency in milliseconds")
    median_ms: float = Field(..., description="Median latency in milliseconds")
    p95_ms: float = Field(..., description="95th percentile latency in milliseconds")
    p99_ms: float = Field(..., description="99th percentile latency in milliseconds")
    min_ms: float = Field(..., description="Minimum latency in milliseconds")
    max_ms: float = Field(..., description="Maximum latency in milliseconds")


class CostMetrics(BaseModel):
    """Cost performance metrics."""
    total_cost: float = Field(..., description="Total cost in USD")
    average_cost_per_evaluation: float = Field(..., description="Average cost per evaluation")
    total_tokens: int = Field(..., description="Total tokens used")
    average_tokens_per_evaluation: float = Field(..., description="Average tokens per evaluation")


class VersionPerformance(BaseModel):
    """Performance metrics for a single prompt version."""
    version_id: str = Field(..., description="ID of the prompt version")
    version_label: str = Field(..., description="Label for the version (e.g., '1.0.0')")
    overall_score: float = Field(..., description="Overall performance score (0.0 to 1.0)")
    pass_rate: float = Field(..., description="Pass rate across all evaluations")
    latency_metrics: LatencyMetrics = Field(..., description="Latency performance")
    cost_metrics: CostMetrics = Field(..., description="Cost metrics")
    rubric_summaries: List[RubricSummary] = Field(default_factory=list, description="Per-rubric summaries")


class ComparisonReport(BaseModel):
    """Structured report comparing two prompt versions."""
    report_id: str = Field(..., description="Unique identifier for the report")
    generated_at: datetime = Field(default_factory=datetime.utcnow, description="Report generation timestamp")
    evaluation_run_id: str = Field(..., description="ID of the evaluation run")
    version_a: VersionPerformance = Field(..., description="Performance of version A")
    version_b: Optional[VersionPerformance] = Field(default=None, description="Performance of version B")
    comparison_summary: Dict[str, Any] = Field(default_factory=dict, description="Summary comparison metrics")
    recommendations: List[str] = Field(default_factory=list, description="Actionable recommendations")
    detailed_findings: List[str] = Field(default_factory=list, description="Detailed findings and insights")


class EvaluationReportGenerator:
    """Generates structured evaluation reports from raw evaluation data."""
    
    def __init__(self):
        pass

    def generate_single_version_report(
        self,
        evaluation_results: List[Dict[str, Any]],
        version_id: str,
        version_label: str,
        evaluation_run_id: str,
    ) -> VersionPerformance:
        """Generate a performance report for a single prompt version.
        
        Args:
            evaluation_results: Raw evaluation results
            version_id: ID of the prompt version
            version_label: Label for the version
            evaluation_run_id: ID of the evaluation run
            
        Returns:
            VersionPerformance: Structured performance metrics
        """
        # Filter successful results
        successful_results = [r for r in evaluation_results if r.get("success")]
        
        if not successful_results:
            logger.warning("No successful evaluation results for report generation")
            return self._empty_version_performance(version_id, version_label)
        
        # Calculate overall score
        overall_score = self._calculate_overall_score(successful_results)
        
        # Calculate pass rate
        pass_rate = sum(1 for r in successful_results if r.get("passed")) / len(successful_results)
        
        # Calculate latency metrics
        latencies = [r.get("latency_ms", 0) for r in successful_results]
        latency_metrics = self._calculate_latency_metrics(latencies)
        
        # Calculate cost metrics
        cost_metrics = self._calculate_cost_metrics(successful_results)
        
        # Calculate rubric summaries
        rubric_summaries = self._calculate_rubric_summaries(successful_results)
        
        return VersionPerformance(
            version_id=version_id,
            version_label=version_label,
            overall_score=overall_score,
            pass_rate=pass_rate,
            latency_metrics=latency_metrics,
            cost_metrics=cost_metrics,
            rubric_summaries=rubric_summaries,
        )

    def generate_comparison_report(
        self,
        results_a: List[Dict[str, Any]],
        results_b: Optional[List[Dict[str, Any]]],
        version_a_id: str,
        version_a_label: str,
        version_b_id: Optional[str],
        version_b_label: Optional[str],
        evaluation_run_id: str,
    ) -> ComparisonReport:
        """Generate a comprehensive comparison report between two versions.
        
        Args:
            results_a: Evaluation results for version A
            results_b: Evaluation results for version B (optional)
            version_a_id: ID of version A
            version_a_label: Label for version A
            version_b_id: ID of version B (optional)
            version_b_label: Label for version B (optional)
            evaluation_run_id: ID of the evaluation run
            
        Returns:
            ComparisonReport: Structured comparison report
        """
        # Generate individual version reports
        version_a_report = self.generate_single_version_report(
            results_a, version_a_id, version_a_label, evaluation_run_id
        )
        
        version_b_report = None
        if results_b and version_b_id and version_b_label:
            version_b_report = self.generate_single_version_report(
                results_b, version_b_id, version_b_label, evaluation_run_id
            )
        
        # Generate comparison summary
        comparison_summary = self._generate_comparison_summary(
            version_a_report, version_b_report
        )
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            version_a_report, version_b_report, comparison_summary
        )
        
        # Generate detailed findings
        detailed_findings = self._generate_detailed_findings(
            version_a_report, version_b_report
        )
        
        return ComparisonReport(
            report_id=f"report_{evaluation_run_id}_{datetime.utcnow().timestamp()}",
            generated_at=datetime.utcnow(),
            evaluation_run_id=evaluation_run_id,
            version_a=version_a_report,
            version_b=version_b_report,
            comparison_summary=comparison_summary,
            recommendations=recommendations,
            detailed_findings=detailed_findings,
        )

    def _calculate_overall_score(self, results: List[Dict[str, Any]]) -> float:
        """Calculate overall score from evaluation results."""
        scores = [r.get("overall_score", 0.0) for r in results if r.get("success")]
        return sum(scores) / len(scores) if scores else 0.0

    def _calculate_latency_metrics(self, latencies: List[float]) -> LatencyMetrics:
        """Calculate latency metrics from latency values."""
        if not latencies:
            return LatencyMetrics(
                average_ms=0.0,
                median_ms=0.0,
                p95_ms=0.0,
                p99_ms=0.0,
                min_ms=0.0,
                max_ms=0.0,
            )
        
        sorted_latencies = sorted(latencies)
        n = len(sorted_latencies)
        
        return LatencyMetrics(
            average_ms=sum(sorted_latencies) / n,
            median_ms=sorted_latencies[n // 2],
            p95_ms=sorted_latencies[int(n * 0.95)] if n > 0 else 0.0,
            p99_ms=sorted_latencies[int(n * 0.99)] if n > 0 else 0.0,
            min_ms=min(sorted_latencies),
            max_ms=max(sorted_latencies),
        )

    def _calculate_cost_metrics(self, results: List[Dict[str, Any]]) -> CostMetrics:
        """Calculate cost metrics from evaluation results."""
        total_cost = sum(r.get("estimated_cost", 0.0) for r in results)
        total_tokens = 0
        
        for r in results:
            token_usage = r.get("token_usage", {})
            if token_usage:
                total_tokens += token_usage.get("total_tokens", 0)
        
        n = len(results)
        
        return CostMetrics(
            total_cost=total_cost,
            average_cost_per_evaluation=total_cost / n if n > 0 else 0.0,
            total_tokens=total_tokens,
            average_tokens_per_evaluation=total_tokens / n if n > 0 else 0.0,
        )

    def _calculate_rubric_summaries(self, results: List[Dict[str, Any]]) -> List[RubricSummary]:
        """Calculate per-rubric summaries from evaluation results."""
        rubric_data: Dict[str, Dict[str, Any]] = {}
        
        for result in results:
            rubric_results = result.get("rubric_results", [])
            for rubric_result in rubric_results:
                rubric_name = rubric_result.get("rubric_name", "unknown")
                
                if rubric_name not in rubric_data:
                    rubric_data[rubric_name] = {
                        "total": 0,
                        "passed": 0,
                        "failed": 0,
                        "confidences": [],
                        "failures": [],
                    }
                
                rubric_data[rubric_name]["total"] += 1
                if rubric_result.get("passed"):
                    rubric_data[rubric_name]["passed"] += 1
                else:
                    rubric_data[rubric_name]["failed"] += 1
                    rubric_data[rubric_name]["failures"].append(
                        rubric_result.get("reasoning", "")
                    )
                
                rubric_data[rubric_name]["confidences"].append(
                    rubric_result.get("confidence_score", 0.5)
                )
        
        summaries = []
        for rubric_name, data in rubric_data.items():
            total = data["total"]
            avg_confidence = sum(data["confidences"]) / len(data["confidences"]) if data["confidences"] else 0.5
            
            # Extract common failure reasons
            from collections import Counter
            failure_counter = Counter(data["failures"])
            common_failures = [reason for reason, _ in failure_counter.most_common(3)]
            
            summaries.append(RubricSummary(
                rubric_name=rubric_name,
                total_evaluations=total,
                passed_count=data["passed"],
                failed_count=data["failed"],
                pass_rate=data["passed"] / total if total > 0 else 0.0,
                average_confidence=avg_confidence,
                common_failures=common_failures,
            ))
        
        return summaries

    def _generate_comparison_summary(
        self,
        version_a: VersionPerformance,
        version_b: Optional[VersionPerformance],
    ) -> Dict[str, Any]:
        """Generate comparison summary between two versions."""
        summary = {
            "version_a_better": False,
            "version_b_better": False,
            "tie": False,
            "score_difference": 0.0,
            "pass_rate_difference": 0.0,
            "latency_difference_ms": 0.0,
            "cost_difference": 0.0,
        }
        
        if version_b is None:
            summary["tie"] = True
            return summary
        
        # Compare overall scores
        score_diff = version_a.overall_score - version_b.overall_score
        summary["score_difference"] = score_diff
        
        if abs(score_diff) < 0.05:
            summary["tie"] = True
        elif score_diff > 0:
            summary["version_a_better"] = True
        else:
            summary["version_b_better"] = True
        
        # Compare pass rates
        summary["pass_rate_difference"] = version_a.pass_rate - version_b.pass_rate
        
        # Compare latencies
        summary["latency_difference_ms"] = (
            version_a.latency_metrics.average_ms - version_b.latency_metrics.average_ms
        )
        
        # Compare costs
        summary["cost_difference"] = (
            version_a.cost_metrics.total_cost - version_b.cost_metrics.total_cost
        )
        
        return summary

    def _generate_recommendations(
        self,
        version_a: VersionPerformance,
        version_b: Optional[VersionPerformance],
        comparison_summary: Dict[str, Any],
    ) -> List[str]:
        """Generate actionable recommendations based on comparison."""
        recommendations = []
        
        if version_b is None:
            recommendations.append("Consider adding a baseline version for comparison")
            return recommendations
        
        # Score-based recommendations
        if comparison_summary["version_a_better"]:
            recommendations.append(
                f"Version A performs better overall (score difference: {comparison_summary['score_difference']:.2f})"
            )
        elif comparison_summary["version_b_better"]:
            recommendations.append(
                f"Version B performs better overall (score difference: {abs(comparison_summary['score_difference']):.2f})"
            )
        else:
            recommendations.append("Both versions perform similarly - consider other factors")
        
        # Latency-based recommendations
        latency_diff = comparison_summary["latency_difference_ms"]
        if abs(latency_diff) > 100:  # More than 100ms difference
            if latency_diff > 0:
                recommendations.append(
                    f"Version B is significantly faster ({abs(latency_diff):.0f}ms average difference)"
                )
            else:
                recommendations.append(
                    f"Version A is significantly faster ({abs(latency_diff):.0f}ms average difference)"
                )
        
        # Cost-based recommendations
        cost_diff = comparison_summary["cost_difference"]
        if abs(cost_diff) > 0.01:  # More than 1 cent difference
            if cost_diff > 0:
                recommendations.append(
                    f"Version B is more cost-effective (${abs(cost_diff):.4f} difference)"
                )
            else:
                recommendations.append(
                    f"Version A is more cost-effective (${abs(cost_diff):.4f} difference)"
                )
        
        # Rubric-specific recommendations
        for rubric in version_a.rubric_summaries:
            if rubric.pass_rate < 0.8:
                recommendations.append(
                    f"Version A struggles with {rubric.rubric_name} (pass rate: {rubric.pass_rate:.1%})"
                )
        
        if version_b:
            for rubric in version_b.rubric_summaries:
                if rubric.pass_rate < 0.8:
                    recommendations.append(
                        f"Version B struggles with {rubric.rubric_name} (pass rate: {rubric.pass_rate:.1%})"
                    )
        
        return recommendations

    def _generate_detailed_findings(
        self,
        version_a: VersionPerformance,
        version_b: Optional[VersionPerformance],
    ) -> List[str]:
        """Generate detailed findings from evaluation results."""
        findings = []
        
        # Version A findings
        findings.append(f"Version A achieved {version_a.overall_score:.2%} overall score")
        findings.append(f"Version A pass rate: {version_a.pass_rate:.1%}")
        findings.append(
            f"Version A average latency: {version_a.latency_metrics.average_ms:.0f}ms "
            f"(P95: {version_a.latency_metrics.p95_ms:.0f}ms)"
        )
        findings.append(
            f"Version A total cost: ${version_a.cost_metrics.total_cost:.4f} "
            f"({version_a.cost_metrics.total_tokens:,} tokens)"
        )
        
        # Rubric-specific findings for version A
        for rubric in version_a.rubric_summaries:
            findings.append(
                f"Version A {rubric.rubric_name}: {rubric.pass_rate:.1%} pass rate "
                f"(avg confidence: {rubric.average_confidence:.2f})"
            )
            if rubric.common_failures:
                findings.append(
                    f"  Common failures in {rubric.rubric_name}: {', '.join(rubric.common_failures[:2])}"
                )
        
        # Version B findings if available
        if version_b:
            findings.append(f"Version B achieved {version_b.overall_score:.2%} overall score")
            findings.append(f"Version B pass rate: {version_b.pass_rate:.1%}")
            findings.append(
                f"Version B average latency: {version_b.latency_metrics.average_ms:.0f}ms "
                f"(P95: {version_b.latency_metrics.p95_ms:.0f}ms)"
            )
            findings.append(
                f"Version B total cost: ${version_b.cost_metrics.total_cost:.4f} "
                f"({version_b.cost_metrics.total_tokens:,} tokens)"
            )
            
            for rubric in version_b.rubric_summaries:
                findings.append(
                    f"Version B {rubric.rubric_name}: {rubric.pass_rate:.1%} pass rate "
                    f"(avg confidence: {rubric.average_confidence:.2f})"
                )
                if rubric.common_failures:
                    findings.append(
                        f"  Common failures in {rubric.rubric_name}: {', '.join(rubric.common_failures[:2])}"
                    )
        
        return findings

    def _empty_version_performance(self, version_id: str, version_label: str) -> VersionPerformance:
        """Create an empty version performance object when no results are available."""
        return VersionPerformance(
            version_id=version_id,
            version_label=version_label,
            overall_score=0.0,
            pass_rate=0.0,
            latency_metrics=LatencyMetrics(
                average_ms=0.0,
                median_ms=0.0,
                p95_ms=0.0,
                p99_ms=0.0,
                min_ms=0.0,
                max_ms=0.0,
            ),
            cost_metrics=CostMetrics(
                total_cost=0.0,
                average_cost_per_evaluation=0.0,
                total_tokens=0,
                average_tokens_per_evaluation=0.0,
            ),
            rubric_summaries=[],
        )
