"""Add tags field to prompts table

Revision ID: add_tags_to_prompts
Revises: 
Create Date: 2026-05-28 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_tags_to_prompts'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add tags column to prompts table."""
    op.add_column(
        'prompts',
        sa.Column(
            'tags',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]',
            nullable=False
        )
    )


def downgrade() -> None:
    """Remove tags column from prompts table."""
    op.drop_column('prompts', 'tags')
