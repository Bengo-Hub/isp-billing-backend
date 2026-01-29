"""Add API credentials storage for reprovisioning

Revision ID: add_router_credentials
Revises: previous_revision
Create Date: 2026-01-27 18:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_router_credentials'
down_revision = '7c4d19524c5d'  # Depends on initial migration
branch_labels = None
depends_on = None


def upgrade():
    # Add columns for storing encrypted API credentials and provisioning status
    op.add_column('routers', sa.Column('api_credentials_encrypted', sa.Text(), nullable=True))
    op.add_column('routers', sa.Column('last_provisioned_at', sa.DateTime(), nullable=True))
    op.add_column('routers', sa.Column('provisioning_status', sa.String(50), nullable=True, server_default='pending'))
    op.add_column('routers', sa.Column('bootstrap_completed', sa.Boolean(), nullable=True, server_default='false'))
    
    # Add index for faster queries on provisioning status
    op.create_index('idx_routers_provisioning_status', 'routers', ['provisioning_status'])


def downgrade():
    op.drop_index('idx_routers_provisioning_status', 'routers')
    op.drop_column('routers', 'bootstrap_completed')
    op.drop_column('routers', 'provisioning_status')
    op.drop_column('routers', 'last_provisioned_at')
    op.drop_column('routers', 'api_credentials_encrypted')
