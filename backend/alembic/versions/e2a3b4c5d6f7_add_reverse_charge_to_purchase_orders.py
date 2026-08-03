"""add reverse_charge to purchase_orders

Revision ID: e2a3b4c5d6f7
Revises: d1f2a3b4c5e6
Create Date: 2026-07-31 10:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e2a3b4c5d6f7'
down_revision: Union[str, Sequence[str], None] = 'd1f2a3b4c5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('purchase_orders', sa.Column('reverse_charge', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('purchase_orders', 'reverse_charge')