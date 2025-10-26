"""merge_multiple_heads

Revision ID: 402f80a6d1a7
Revises: 3aae684d6ae6, add_rbac_tables
Create Date: 2025-10-21 13:37:41.835211

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '402f80a6d1a7'
down_revision = ('3aae684d6ae6', 'add_rbac_tables')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
