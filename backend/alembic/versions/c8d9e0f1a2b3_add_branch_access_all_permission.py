"""add branch.access_all permission for cross-branch override

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-08-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, Sequence[str], None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO permissions (id, perm_code, module, action, description)
        VALUES (
            uuid_generate_v4(), 'branch.access_all', 'branch', 'access_all',
            'Act across all branches even when assigned to a specific branch (e.g. regional manager)'
        )
        ON CONFLICT (perm_code) DO NOTHING;
    """)

    # Grant it to Super Admin / Admin so nothing that already worked breaks —
    # their role already has full branch.* CRUD, this just adds the override.
    op.execute("""
        INSERT INTO role_permissions (role_id, perm_id)
        SELECT r.id, p.id
        FROM roles r, permissions p
        WHERE p.perm_code = 'branch.access_all'
          AND r.role_name IN ('Super Admin', 'Admin')
          AND NOT EXISTS (
              SELECT 1 FROM role_permissions rp
              WHERE rp.role_id = r.id AND rp.perm_id = p.id
          );
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM role_permissions WHERE perm_id IN (
            SELECT id FROM permissions WHERE perm_code = 'branch.access_all'
        );
    """)
    op.execute("DELETE FROM permissions WHERE perm_code = 'branch.access_all';")