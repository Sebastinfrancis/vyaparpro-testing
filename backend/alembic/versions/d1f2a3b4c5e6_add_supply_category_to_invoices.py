"""add supply_category to invoices

Revision ID: d1f2a3b4c5e6
Revises: a4b697705c15
Create Date: 2026-07-31 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1f2a3b4c5e6'
down_revision: Union[str, Sequence[str], None] = 'a4b697705c15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('invoices', sa.Column('supply_category', sa.String(length=20), nullable=False, server_default='taxable'))


def downgrade() -> None:
    op.drop_column('invoices', 'supply_category')