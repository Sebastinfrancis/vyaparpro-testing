"""add branch_id to gst_returns so each branch/GSTIN files separately

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-08-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9e0f1a2b3c4'
down_revision: Union[str, Sequence[str], None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c['name'] for c in inspector.get_columns('gst_returns')}

    if 'branch_id' not in columns:
        op.add_column('gst_returns', sa.Column('branch_id', sa.dialects.postgresql.UUID(as_uuid=True),
                                                 sa.ForeignKey('branches.id'), nullable=True))

    existing_indexes = {ix['name'] for ix in inspector.get_indexes('gst_returns')}
    if 'ix_gst_returns_branch_id' not in existing_indexes:
        op.create_index('ix_gst_returns_branch_id', 'gst_returns', ['branch_id'])

    # The old constraint only allowed one filing per (company, return_type, period) —
    # correct for a single-GSTIN company, but wrong once a company has multiple
    # branch GSTINs each needing to file the same period separately. Find whatever
    # that constraint is actually named (rather than assuming) and replace it.
    existing_uniques = inspector.get_unique_constraints('gst_returns')
    old_constraint_name = None
    for uc in existing_uniques:
        if set(uc['column_names']) == {'company_id', 'return_type', 'period_from'}:
            old_constraint_name = uc['name']
            break

    already_has_new_constraint = any(
        set(uc['column_names']) == {'company_id', 'branch_id', 'return_type', 'period_from'}
        for uc in existing_uniques
    )

    if old_constraint_name and not already_has_new_constraint:
        op.drop_constraint(old_constraint_name, 'gst_returns', type_='unique')
    if not already_has_new_constraint:
        op.create_unique_constraint(
            'uq_gst_returns_company_branch_type_period',
            'gst_returns', ['company_id', 'branch_id', 'return_type', 'period_from'],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_uniques = {uc['name'] for uc in inspector.get_unique_constraints('gst_returns')}
    if 'uq_gst_returns_company_branch_type_period' in existing_uniques:
        op.drop_constraint('uq_gst_returns_company_branch_type_period', 'gst_returns', type_='unique')
        op.create_unique_constraint(
            'gst_returns_company_id_return_type_period_from_key',
            'gst_returns', ['company_id', 'return_type', 'period_from'],
        )
    existing_indexes = {ix['name'] for ix in inspector.get_indexes('gst_returns')}
    if 'ix_gst_returns_branch_id' in existing_indexes:
        op.drop_index('ix_gst_returns_branch_id', table_name='gst_returns')
    columns = {c['name'] for c in inspector.get_columns('gst_returns')}
    if 'branch_id' in columns:
        op.drop_column('gst_returns', 'branch_id')