"""add crm leads table

Revision ID: f582646e8b1b
Revises: acc01e03b47e
Create Date: 2026-07-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f582646e8b1b'
down_revision: Union[str, Sequence[str], None] = 'acc01e03b47e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'crm_leads',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('party_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('parties.id'), nullable=True),
        sa.Column('lead_name', sa.String(200), nullable=False),
        sa.Column('company_name', sa.String(200), nullable=True),
        sa.Column('mobile', sa.String(20), nullable=True),
        sa.Column('email', sa.String(150), nullable=True),
        sa.Column('stage', sa.String(30), nullable=False, server_default='New'),
        sa.Column('value', sa.Numeric(15, 2), nullable=False, server_default='0'),
        sa.Column('follow_up_date', sa.Date(), nullable=True),
        sa.Column('ai_suggestion', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_table('crm_leads')