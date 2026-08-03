"""merge heads

Revision ID: e6b24d951c6e
Revises: c9e12a4f6b21, f3b4c5d6e7a8
Create Date: 2026-08-03 12:03:07.923564

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6b24d951c6e'
down_revision: Union[str, Sequence[str], None] = ('c9e12a4f6b21', 'f3b4c5d6e7a8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
