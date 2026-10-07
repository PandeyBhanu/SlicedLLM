# Import all models so that Base.metadata has them before Alembic / create_all run.
from app.models.base import Base  # noqa
from app.models.prompt import Prompt, PromptVersion  # noqa
from app.models.evaluation import (  # noqa
    CandidateOutput,
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    JudgeEvaluation,
    Rubric,
    RubricScore,
)
from app.models.audit import AuditLog  # noqa
from app.db import ddl  # noqa  (registers triggers on Base.metadata)
