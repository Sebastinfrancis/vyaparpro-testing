"""add current_stock to products

Revision ID: acc01e03b47e
Revises: b0a10fb064de
Create Date: 2026-07-07 17:36:03.494370

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'acc01e03b47e'
down_revision: Union[str, Sequence[str], None] = 'b0a10fb064de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column(
        'current_stock',
        sa.Numeric(precision=15, scale=4),
        server_default='0',
        nullable=False
    ))

def downgrade() -> None:
    op.drop_column('products', 'current_stock')