"""add export fields to invoices

Revision ID: a4b697705c15
Revises: 38bfca197a4d
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a4b697705c15'
down_revision: Union[str, Sequence[str], None] = '38bfca197a4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('invoices', sa.Column('is_export', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('invoices', sa.Column('export_type', sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column('invoices', 'export_type')
    op.drop_column('invoices', 'is_export')