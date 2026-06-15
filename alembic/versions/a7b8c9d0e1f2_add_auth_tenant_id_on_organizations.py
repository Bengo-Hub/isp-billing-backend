"""add auth_tenant_id on organizations

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-15 16:00:00.000000

Auth-api tenant linkage (ADDITIVE): auth-api is the source of truth for ISP
providers (they sign up via SSO). It publishes ``auth.tenant.created`` and
``auth.user.*`` which isp-billing consumes (app/events/consumer.py) to upsert a
local Organization + Users keyed by the auth tenant UUID. This adds a nullable,
unique, indexed ``auth_tenant_id`` column to ``organizations``.

Guarded-additive: the column add + index are wrapped in inspector checks so a
re-run on a partially-migrated DB is a no-op rather than an error (matching the
repo's idempotent-on-startup migration convention). Nullable, so existing
local-only orgs are unaffected.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def _columns(table: str) -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {c['name'] for c in inspector.get_columns(table)}


def _indexes(table: str) -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {ix['name'] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    if 'auth_tenant_id' not in _columns('organizations'):
        op.add_column(
            'organizations',
            sa.Column('auth_tenant_id', sa.String(length=36), nullable=True),
        )

    if 'ix_organizations_auth_tenant_id' not in _indexes('organizations'):
        # Unique index (also enforces uniqueness for the nullable column;
        # Postgres treats NULLs as distinct, so multiple local-only orgs are OK).
        op.create_index(
            'ix_organizations_auth_tenant_id',
            'organizations',
            ['auth_tenant_id'],
            unique=True,
        )


def downgrade() -> None:
    if 'ix_organizations_auth_tenant_id' in _indexes('organizations'):
        op.drop_index('ix_organizations_auth_tenant_id', table_name='organizations')
    if 'auth_tenant_id' in _columns('organizations'):
        op.drop_column('organizations', 'auth_tenant_id')
