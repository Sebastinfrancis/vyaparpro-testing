"""move product.* permissions from module 'inventory' to their own 'product' module

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # These were seeded with module='inventory' by mistake in init.sql, which
    # makes the role-editor UI merge them with the real inventory.* (stock
    # movement) permissions under one "Inventory" heading — two different
    # 'read'/'create'/'delete'/'update' checkboxes render identically with
    # no way to tell them apart. Endpoints already check the correct,
    # distinct perm_codes; this only fixes how they're grouped for display.
    op.execute("""
        UPDATE permissions SET module = 'product'
        WHERE perm_code IN ('product.create', 'product.read', 'product.update', 'product.delete')
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE permissions SET module = 'inventory'
        WHERE perm_code IN ('product.create', 'product.read', 'product.update', 'product.delete')
    """)