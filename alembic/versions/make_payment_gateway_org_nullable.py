"""Make payment_gateway_configs.organization_id nullable for platform-level gateways.

Revision ID: b8c3f7a2e9d1
Revises: 279ffe74982f
Create Date: 2026-01-29 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8c3f7a2e9d1'
down_revision = '6df4d4bf3799'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make organization_id nullable to support platform-level payment gateways
    # Platform-level gateways (org_id = NULL) collect all customer payments
    op.alter_column(
        'payment_gateway_configs',
        'organization_id',
        existing_type=sa.Integer(),
        nullable=True
    )


def downgrade() -> None:
    # Note: This will fail if there are any platform-level gateways (NULL organization_id)
    op.alter_column(
        'payment_gateway_configs',
        'organization_id',
        existing_type=sa.Integer(),
        nullable=False
    )
