"""Add hotspot user generation settings to organization_settings.

Revision ID: c9d4e8f3a1b2
Revises: b8c3f7a2e9d1
Create Date: 2026-01-31 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9d4e8f3a1b2'
down_revision = 'b8c3f7a2e9d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add hotspot user generation settings
    # These settings control how hotspot usernames are auto-generated when users purchase packages

    # Username prefix (e.g., "C" -> C001, C002, C003)
    op.add_column(
        'organization_settings',
        sa.Column('hotspot_username_prefix', sa.String(10), nullable=False, server_default='C')
    )

    # Auto-increment counter for generating unique usernames
    op.add_column(
        'organization_settings',
        sa.Column('hotspot_username_counter', sa.Integer(), nullable=False, server_default='1')
    )

    # Hotspot login page template name (e.g., "Aurora", "Modern", "Classic")
    op.add_column(
        'organization_settings',
        sa.Column('hotspot_template', sa.String(50), nullable=False, server_default='Aurora')
    )

    # Days after which to auto-delete inactive hotspot users
    op.add_column(
        'organization_settings',
        sa.Column('prune_inactive_users_days', sa.Integer(), nullable=False, server_default='14')
    )

    # Redirect URL after successful login/purchase
    op.add_column(
        'organization_settings',
        sa.Column('hotspot_redirect_url', sa.String(500), nullable=False, server_default='https://www.google.com')
    )


def downgrade() -> None:
    op.drop_column('organization_settings', 'hotspot_redirect_url')
    op.drop_column('organization_settings', 'prune_inactive_users_days')
    op.drop_column('organization_settings', 'hotspot_template')
    op.drop_column('organization_settings', 'hotspot_username_counter')
    op.drop_column('organization_settings', 'hotspot_username_prefix')
