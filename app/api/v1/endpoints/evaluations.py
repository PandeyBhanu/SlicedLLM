import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_evaluation_service
from app.schemas.evaluation import (
    ComparisonReportSchema,
    EvaluationHistoryResponse,
    EvaluationRunCreate,
    EvaluationRunResponse,
)
from app.services.evaluation import EvaluationService

router = APIRouter()


@router.post("/runs", response_model=EvaluationRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def execute_evaluation_run(
    schema: EvaluationRunCreate,
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Trigger an async evaluation run comparing prompt versions across a dataset."""
    return await service.execute_evaluation_run(schema)


@router.get("/runs/{id}", response_model=EvaluationRunResponse)
async def get_evaluation_run(
    id: uuid.UUID,
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Retrieve detailed execution status, latencies, cost, and results of an evaluation run."""
    return await service.get_evaluation_run(id)


@router.get("/runs/{id}/report", response_model=ComparisonReportSchema)
async def get_evaluation_report(
    id: uuid.UUID,
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Generate a structured evaluation report for a completed run."""
    report = await service.generate_evaluation_report(id)
    return report


@router.get("/history", response_model=List[EvaluationHistoryResponse])
async def get_evaluation_history(
    prompt_id: Optional[uuid.UUID] = Query(None, description="Filter by prompt ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    service: EvaluationService = Depends(get_evaluation_service),
):
    """Retrieve evaluation history with aggregated statistics."""
    history = await service.get_evaluation_history(prompt_id=prompt_id, skip=skip, limit=limit)
    return history
