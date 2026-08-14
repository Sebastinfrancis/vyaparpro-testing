"""add branch manager/head-office/target fields and branch-level bank accounts

Revision ID: f1a2b3c4d5e6
Revises: d9e0f1a2b3c4
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'd9e0f1a2b3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Branch — gaps #2, #3, #5
    op.add_column('branches', sa.Column('is_head_office', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('branches', sa.Column('manager_user_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('branches', sa.Column('manager_name', sa.String(120), nullable=True))
    op.add_column('branches', sa.Column('manager_phone', sa.String(20), nullable=True))
    op.add_column('branches', sa.Column('monthly_target', sa.Numeric(15, 2), nullable=False, server_default='0'))
    op.create_foreign_key('fk_branches_manager_user_id', 'branches', 'users', ['manager_user_id'], ['id'])

    # One Head Office per company — partial unique index.
    op.execute("""
        CREATE UNIQUE INDEX uq_branches_one_head_office
        ON branches (company_id)
        WHERE is_head_office = TRUE AND is_active = TRUE
    """)

    # Accounts — gap #4
    op.add_column('accounts', sa.Column('branch_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_accounts_branch_id', 'accounts', 'branches', ['branch_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_accounts_branch_id', 'accounts', type_='foreignkey')
    op.drop_column('accounts', 'branch_id')

    op.execute("DROP INDEX IF EXISTS uq_branches_one_head_office")

    op.drop_constraint('fk_branches_manager_user_id', 'branches', type_='foreignkey')
    op.drop_column('branches', 'monthly_target')
    op.drop_column('branches', 'manager_phone')
    op.drop_column('branches', 'manager_name')
    op.drop_column('branches', 'manager_user_id')
    op.drop_column('branches', 'is_head_office')