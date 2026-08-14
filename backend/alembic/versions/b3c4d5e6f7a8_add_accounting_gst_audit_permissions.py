"""add accounting, gst, and audit permission modules

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # accounting.py, gst.py and audit.py had zero permission checks — there was no
    # permission module for them to check against. This adds one for each.
    op.execute("""
        INSERT INTO permissions (perm_code, module, action, description) VALUES
          ('accounting.create', 'accounting', 'create', 'Create accounts, account groups, and journal vouchers'),
          ('accounting.read',   'accounting', 'read',   'View chart of accounts, ledgers, vouchers and accounting reports'),
          ('accounting.update', 'accounting', 'update', 'Update accounts and account groups'),
          ('accounting.post',   'accounting', 'post',   'Post a journal voucher to the ledger'),
          ('accounting.reverse','accounting', 'reverse','Reverse a posted journal voucher'),
          ('gst.read',   'gst', 'read',   'View GST summary, GSTR-1, GSTR-3B, HSN summary and ITC ledger'),
          ('gst.file',   'gst', 'file',   'File GSTR-3B for a period (locks the period)'),
          ('gst.export', 'gst', 'export', 'Download GST reports as PDF or export GSTR-1 JSON'),
          ('audit.read', 'audit', 'read', 'View the audit log')
        ON CONFLICT (perm_code) DO NOTHING;
    """)

    # Backfill: existing full-access (level 1) roles — e.g. the "super admin" role
    # created automatically at sign-up by bootstrap_admin.py — get the new
    # permissions too, so they aren't locked out of modules they already had
    # unrestricted access to before this migration.
    op.execute("""
        INSERT INTO role_permissions (role_id, perm_id, granted_by)
        SELECT r.id, p.id, NULL
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.role_level = 1
          AND p.perm_code IN (
            'accounting.create', 'accounting.read', 'accounting.update',
            'accounting.post', 'accounting.reverse',
            'gst.read', 'gst.file', 'gst.export',
            'audit.read'
          )
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM role_permissions WHERE perm_id IN (
            SELECT id FROM permissions WHERE perm_code IN (
                'accounting.create', 'accounting.read', 'accounting.update',
                'accounting.post', 'accounting.reverse',
                'gst.read', 'gst.file', 'gst.export',
                'audit.read'
            )
        );
    """)
    op.execute("""
        DELETE FROM permissions WHERE perm_code IN (
            'accounting.create', 'accounting.read', 'accounting.update',
            'accounting.post', 'accounting.reverse',
            'gst.read', 'gst.file', 'gst.export',
            'audit.read'
        );
    """)