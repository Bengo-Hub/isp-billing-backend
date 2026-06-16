"""add file_data blob on router_backups

Stores the actual .backup file uploaded NAT-safely by the polling agent so
backups are downloadable from the platform (previously the file stayed on the
router). Rows + blobs are churned after 2 days by a Celery task.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd0e1f2a3b4c5'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'router_backups',
        sa.Column('file_data', sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('router_backups', 'file_data')
