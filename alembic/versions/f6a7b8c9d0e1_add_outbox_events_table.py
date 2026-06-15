"""add outbox_events table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-15 14:00:00.000000

Phase 5 (ADDITIVE): transactional outbox for NATS/JetStream event integration.
Domain operations write an ``outbox_events`` row in the same transaction as the
business change; a Celery beat poller publishes unpublished rows to NATS and
stamps ``published_at``.

Brand-new table, no FKs, nothing else references it — so this is purely additive
and safe to apply ahead of enabling NATS. ``create_table`` is guarded with an
inspector check so a re-run on a partially-migrated DB is a no-op rather than an
error (matching the repo's idempotent-on-startup migration convention).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def _existing_indexes(table: str) -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {ix['name'] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    if not _has_table('outbox_events'):
        op.create_table(
            'outbox_events',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('aggregate_type', sa.String(length=64), nullable=False, server_default='isp'),
            sa.Column('aggregate_id', sa.String(length=128), nullable=True),
            sa.Column('event_type', sa.String(length=128), nullable=False),
            sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column('tenant_id', sa.String(length=64), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('published_at', sa.DateTime(), nullable=True),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.PrimaryKeyConstraint('id'),
        )

    indexes = _existing_indexes('outbox_events')
    if 'ix_outbox_events_tenant_id' not in indexes:
        op.create_index('ix_outbox_events_tenant_id', 'outbox_events', ['tenant_id'], unique=False)
    if 'ix_outbox_events_created_at' not in indexes:
        op.create_index('ix_outbox_events_created_at', 'outbox_events', ['created_at'], unique=False)
    if 'ix_outbox_events_published_at' not in indexes:
        op.create_index('ix_outbox_events_published_at', 'outbox_events', ['published_at'], unique=False)


def downgrade() -> None:
    if _has_table('outbox_events'):
        indexes = _existing_indexes('outbox_events')
        for ix in (
            'ix_outbox_events_published_at',
            'ix_outbox_events_created_at',
            'ix_outbox_events_tenant_id',
        ):
            if ix in indexes:
                op.drop_index(ix, table_name='outbox_events')
        op.drop_table('outbox_events')
