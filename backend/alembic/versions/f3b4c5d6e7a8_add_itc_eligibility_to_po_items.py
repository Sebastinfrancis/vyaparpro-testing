"""add itc eligibility fields to purchase_order_items

Revision ID: f3b4c5d6e7a8
Revises: e2a3b4c5d6f7
Create Date: 2026-07-31 10:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3b4c5d6e7a8'
down_revision: Union[str, Sequence[str], None] = 'e2a3b4c5d6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('purchase_order_items', sa.Column('itc_eligible', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('purchase_order_items', sa.Column('itc_ineligible_reason', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('purchase_order_items', 'itc_ineligible_reason')
    op.drop_column('purchase_order_items', 'itc_eligible')