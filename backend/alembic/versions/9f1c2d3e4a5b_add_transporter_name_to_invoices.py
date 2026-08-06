"""add transporter_name to invoices

Revision ID: 9f1c2d3e4a5b
Revises: 'a1c2d3e4f5b6'
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f1c2d3e4a5b'
down_revision: Union[str, Sequence[str], None] = 'a1c2d3e4f5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('invoices', sa.Column('transporter_name', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('invoices', 'transporter_name')