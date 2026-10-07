import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_evaluation_service
from app.schemas.evaluation import (
    CaseResultResponse,
    EvaluationRunCreate,
    EvaluationRunResponse,
    RubricCreate,
    RubricResponse,
    RunSummary,
)
from app.services.evaluation import EvaluationService

router = APIRouter()


@router.post("/runs", response_model=EvaluationRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    schema: EvaluationRunCreate, service: EvaluationService = Depends(get_evaluation_service)
):
    """Enqueue an A/B run (status PENDING). A background worker executes it; poll GET /runs/{id}."""
    return await service.create_run(schema)


@router.get("/runs", response_model=list[EvaluationRunResponse])
async def list_runs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    service: EvaluationService = Depends(get_evaluation_service),
):
    return await service.list_runs(skip=skip, limit=limit)


@router.get("/runs/{id}", response_model=EvaluationRunResponse)
async def get_run(id: uuid.UUID, service: EvaluationService = Depends(get_evaluation_service)):
    return await service.get_run(id)


@router.post("/runs/{id}/cancel", response_model=EvaluationRunResponse)
async def cancel_run(id: uuid.UUID, service: EvaluationService = Depends(get_evaluation_service)):
    return await service.cancel_run(id)


@router.get("/runs/{id}/summary", response_model=RunSummary)
async def get_summary(id: uuid.UUID, service: EvaluationService = Depends(get_evaluation_service)):
    return await service.get_summary(id)


@router.get("/runs/{id}/cases", response_model=list[CaseResultResponse])
async def get_cases(id: uuid.UUID, service: EvaluationService = Depends(get_evaluation_service)):
    """Per-case outputs of A and B, judge evaluations and rubric scores."""
    return await service.get_cases(id)


@router.get("/rubrics", response_model=list[RubricResponse])
async def list_rubrics(service: EvaluationService = Depends(get_evaluation_service)):
    return await service.list_rubrics()


@router.post("/rubrics", response_model=RubricResponse, status_code=status.HTTP_201_CREATED)
async def create_rubric(
    schema: RubricCreate, service: EvaluationService = Depends(get_evaluation_service)
):
    return await service.create_rubric(schema)
