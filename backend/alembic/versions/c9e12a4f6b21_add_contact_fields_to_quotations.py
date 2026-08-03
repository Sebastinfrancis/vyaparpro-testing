"""add contact_phone and contact_email to quotations

Revision ID: c9e12a4f6b21
Revises: a4b697705c15
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9e12a4f6b21'
down_revision: Union[str, Sequence[str], None] = 'a4b697705c15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quotations', sa.Column('contact_phone', sa.String(20), nullable=True))
    op.add_column('quotations', sa.Column('contact_email', sa.String(150), nullable=True))


def downgrade() -> None:
    op.drop_column('quotations', 'contact_email')
    op.drop_column('quotations', 'contact_phone')