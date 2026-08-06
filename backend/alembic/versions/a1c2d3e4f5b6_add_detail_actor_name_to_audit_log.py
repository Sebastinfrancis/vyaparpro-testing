"""add detail and actor_name to audit_log

Revision ID: a1c2d3e4f5b6
Revises: e6b24d951c6e
Create Date: 2026-08-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c2d3e4f5b6'
down_revision: Union[str, Sequence[str], None] = 'e6b24d951c6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('audit_log', sa.Column('detail', sa.Text(), nullable=True))
    op.add_column('audit_log', sa.Column('actor_name', sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column('audit_log', 'actor_name')
    op.drop_column('audit_log', 'detail')