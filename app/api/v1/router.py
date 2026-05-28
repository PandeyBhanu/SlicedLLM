from fastapi import APIRouter

from app.api.v1.endpoints import datasets, evaluations, promptops, prompts

api_router = APIRouter()

api_router.include_router(prompts.router, prefix="/prompts", tags=["Prompts"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["Evaluation Datasets"])
api_router.include_router(evaluations.router, prefix="/evaluations", tags=["Evaluation Runs"])
api_router.include_router(promptops.router, prefix="/promptops", tags=["PromptOps"])
