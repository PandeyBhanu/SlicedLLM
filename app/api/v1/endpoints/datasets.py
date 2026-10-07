import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_evaluation_service
from app.schemas.evaluation import (
    EvaluationCaseCreate,
    EvaluationCaseResponse,
    EvaluationDatasetCreate,
    EvaluationDatasetDetail,
    EvaluationDatasetResponse,
)
from app.services.evaluation import EvaluationService

router = APIRouter()


@router.post("", response_model=EvaluationDatasetResponse, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    schema: EvaluationDatasetCreate, service: EvaluationService = Depends(get_evaluation_service)
):
    return await service.create_dataset(schema)


@router.get("", response_model=list[EvaluationDatasetResponse])
async def list_datasets(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    service: EvaluationService = Depends(get_evaluation_service),
):
    return await service.list_datasets(skip=skip, limit=limit)


@router.get("/{id}", response_model=EvaluationDatasetDetail)
async def get_dataset(id: uuid.UUID, service: EvaluationService = Depends(get_evaluation_service)):
    return await service.get_dataset(id)


@router.post(
    "/{id}/cases", response_model=EvaluationCaseResponse, status_code=status.HTTP_201_CREATED
)
async def add_case_to_dataset(
    id: uuid.UUID,
    schema: EvaluationCaseCreate,
    service: EvaluationService = Depends(get_evaluation_service),
):
    return await service.add_case_to_dataset(dataset_id=id, schema=schema)
