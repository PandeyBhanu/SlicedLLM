from fastapi import APIRouter, Depends

from app.api.deps import require_api_key
from app.api.v1.endpoints import audit, datasets, evaluations, prompts

api_router = APIRouter(dependencies=[Depends(require_api_key)])

api_router.include_router(prompts.router, prefix="/prompts", tags=["Prompts"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["Evaluation Datasets"])
api_router.include_router(evaluations.router, prefix="/evaluations", tags=["Evaluations"])
api_router.include_router(audit.router, prefix="/audit", tags=["Audit"])
