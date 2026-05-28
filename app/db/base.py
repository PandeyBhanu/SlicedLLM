# Import all models so that Base.metadata has them before Alembic imports env
from app.models.base import Base  # noqa
from app.models.prompt import Prompt, PromptVersion  # noqa
from app.models.evaluation import (  # noqa
    EvaluationDataset,
    EvaluationCase,
    EvaluationRun,
    EvaluationResult,
)
from app.models.audit import AuditLog  # noqa
