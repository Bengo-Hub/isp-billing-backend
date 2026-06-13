"""add WireGuard VPN overlay columns on routers

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-14 12:00:00.000000

Adds the per-router WireGuard tunnel fields used by the VPN overlay:
- vpn_address     : the router's tunnel IP (10.8.0.<n>), unique
- vpn_public_key  : the router's OWN WG public key (no private material stored)
- vpn_enabled     : whether the tunnel is established and usable

These are additive + nullable so the migration is safe on existing rows. The
backend runs migrations idempotently on container start; ``op.add_column`` is
guarded with an inspector check so a re-run on a partially-migrated DB is a
no-op rather than an error.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def _existing_columns(table: str) -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {c['name'] for c in inspector.get_columns(table)}


def upgrade() -> None:
    cols = _existing_columns('routers')

    if 'vpn_address' not in cols:
        op.add_column('routers', sa.Column('vpn_address', sa.String(length=45), nullable=True))
        op.create_unique_constraint(op.f('uq_routers_vpn_address'), 'routers', ['vpn_address'])
    if 'vpn_public_key' not in cols:
        op.add_column('routers', sa.Column('vpn_public_key', sa.String(length=64), nullable=True))
    if 'vpn_enabled' not in cols:
        op.add_column(
            'routers',
            sa.Column('vpn_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    cols = _existing_columns('routers')
    if 'vpn_enabled' in cols:
        op.drop_column('routers', 'vpn_enabled')
    if 'vpn_public_key' in cols:
        op.drop_column('routers', 'vpn_public_key')
    if 'vpn_address' in cols:
        op.drop_constraint(op.f('uq_routers_vpn_address'), 'routers', type_='unique')
        op.drop_column('routers', 'vpn_address')
