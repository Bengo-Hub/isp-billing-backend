"""Add Winbox remote access columns for VPN tunneling.

Revision ID: d5e6f7g8h9i0
Revises: d0e5f9a4b3c6
Create Date: 2026-01-31 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'd5e6f7g8h9i0'
down_revision = 'd0e5f9a4b3c6'
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    # Add winbox_port to routers table for remote Winbox access via VPN tunnel
    # Each router gets a unique port in the configured range (e.g., 51000-59999)
    if not column_exists('routers', 'winbox_port'):
        op.add_column(
            'routers',
            sa.Column('winbox_port', sa.Integer(), nullable=True)
        )
        # Create unique constraint separately (constraint may already exist from partial run)
        try:
            op.create_unique_constraint('uq_routers_winbox_port', 'routers', ['winbox_port'])
        except Exception:
            pass  # Constraint already exists

    # Add VPN domain configuration to organization_settings
    # This is the domain used for remote Winbox access (e.g., vpn.codevertex.com:51255)
    if not column_exists('organization_settings', 'vpn_domain'):
        op.add_column(
            'organization_settings',
            sa.Column('vpn_domain', sa.String(200), nullable=False, server_default='vpn.codevertex.com')
        )

    # Add port range configuration for Winbox VPN allocation
    if not column_exists('organization_settings', 'winbox_port_start'):
        op.add_column(
            'organization_settings',
            sa.Column('winbox_port_start', sa.Integer(), nullable=False, server_default='51000')
        )

    if not column_exists('organization_settings', 'winbox_port_end'):
        op.add_column(
            'organization_settings',
            sa.Column('winbox_port_end', sa.Integer(), nullable=False, server_default='59999')
        )


def downgrade() -> None:
    # Drop unique constraint first (may not exist)
    try:
        op.drop_constraint('uq_routers_winbox_port', 'routers', type_='unique')
    except Exception:
        pass

    # Drop columns if they exist
    if column_exists('organization_settings', 'winbox_port_end'):
        op.drop_column('organization_settings', 'winbox_port_end')
    if column_exists('organization_settings', 'winbox_port_start'):
        op.drop_column('organization_settings', 'winbox_port_start')
    if column_exists('organization_settings', 'vpn_domain'):
        op.drop_column('organization_settings', 'vpn_domain')
    if column_exists('routers', 'winbox_port'):
        op.drop_column('routers', 'winbox_port')
