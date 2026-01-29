"""Merge migration heads

Revision ID: 279ffe74982f
Revises: 7c4d19524c5d, add_router_credentials
Create Date: 2026-01-27 19:04:52.619115

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '279ffe74982f'
down_revision = 'add_router_credentials'
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
