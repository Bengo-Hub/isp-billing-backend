"""add SSO / JIT provisioning columns on users

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-15 09:00:00.000000

Phase 1b (ADDITIVE): links a local user to its central SSO (auth-api) subject.

- auth_service_user_id : the SSO `sub` claim (uuid as string), unique-nullable
- auth_synced_at       : last time the local user was synced from SSO claims

Both columns are nullable so existing local-only users are unaffected; the
local login + RBAC path keeps working unchanged. ``op.add_column`` is guarded
with an inspector check so a re-run on a partially-migrated DB is a no-op
rather than an error (matching the repo's idempotent-on-startup convention).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def _existing_columns(table: str) -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {c['name'] for c in inspector.get_columns(table)}


def _existing_indexes(table: str) -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {ix['name'] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    cols = _existing_columns('users')

    if 'auth_service_user_id' not in cols:
        op.add_column(
            'users',
            sa.Column('auth_service_user_id', sa.String(length=255), nullable=True),
        )
        # Unique index doubles as the lookup index for JIT linking.
        if 'ix_users_auth_service_user_id' not in _existing_indexes('users'):
            op.create_index(
                'ix_users_auth_service_user_id',
                'users',
                ['auth_service_user_id'],
                unique=True,
            )

    if 'auth_synced_at' not in cols:
        op.add_column(
            'users',
            sa.Column('auth_synced_at', sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    cols = _existing_columns('users')

    if 'auth_synced_at' in cols:
        op.drop_column('users', 'auth_synced_at')

    if 'auth_service_user_id' in cols:
        if 'ix_users_auth_service_user_id' in _existing_indexes('users'):
            op.drop_index('ix_users_auth_service_user_id', table_name='users')
        op.drop_column('users', 'auth_service_user_id')
