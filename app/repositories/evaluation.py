import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)
from app.repositories.base import BaseRepository


class EvaluationDatasetRepository(BaseRepository[EvaluationDataset]):
    """Repository handling custom queries for Evaluation Datasets."""

    def __init__(self, db: AsyncSession):
        super().__init__(EvaluationDataset, db)

    async def get_by_name(self, name: str) -> Optional[EvaluationDataset]:
        """Fetch a dataset by its unique name."""
        query = select(self.model).where(self.model.name == name)
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_with_cases(self, id: uuid.UUID) -> Optional[EvaluationDataset]:
        """Fetch a dataset and eagerly load all its test cases in a single roundtrip."""
        query = (
            select(self.model)
            .where(self.model.id == id)
            .options(selectinload(self.model.cases))
        )
        result = await self.db.execute(query)
        return result.scalars().first()


class EvaluationCaseRepository(BaseRepository[EvaluationCase]):
    """Repository handling custom queries for Evaluation Cases."""

    def __init__(self, db: AsyncSession):
        super().__init__(EvaluationCase, db)

    async def get_by_dataset(self, dataset_id: uuid.UUID) -> List[EvaluationCase]:
        """Fetch all test cases belonging to a dataset."""
        query = select(self.model).where(self.model.dataset_id == dataset_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())


class EvaluationRunRepository(BaseRepository[EvaluationRun]):
    """Repository handling custom queries for Evaluation Runs."""

    def __init__(self, db: AsyncSession):
        super().__init__(EvaluationRun, db)

    async def get_run_with_results(self, id: uuid.UUID) -> Optional[EvaluationRun]:
        """Fetch a run and eagerly load its results and case contexts."""
        query = (
            select(self.model)
            .where(self.model.id == id)
            .options(
                selectinload(self.model.results).selectinload(EvaluationResult.case),
                joinedload(self.model.prompt_version_a),
                joinedload(self.model.prompt_version_b),
            )
        )
        result = await self.db.execute(query)
        return result.scalars().first()


class EvaluationResultRepository(BaseRepository[EvaluationResult]):
    """Repository handling custom queries for Evaluation Results."""

    def __init__(self, db: AsyncSession):
        super().__init__(EvaluationResult, db)

    async def get_by_run(self, run_id: uuid.UUID) -> List[EvaluationResult]:
        """Fetch all results for a run, joining case information."""
        query = (
            select(self.model)
            .where(self.model.evaluation_run_id == run_id)
            .options(joinedload(self.model.case))
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
