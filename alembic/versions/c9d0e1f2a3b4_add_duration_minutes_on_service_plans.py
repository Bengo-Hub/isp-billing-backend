"""add duration_minutes on service_plans

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-16 06:30:00.000000

Adds a precise per-package access duration in MINUTES to service_plans. It is the
authoritative access window when set (> 0), supporting sub-hour and arbitrary
combos (30 = 30min, 90 = 1h30m, 150 = 2h30m, 1440 = 1 day) that the integer
``validity_days`` (days) + ``time_limit`` (hours) columns could not express.
Nullable + additive: existing plans keep using validity_days/time_limit, so this
is a no-op for them.

Guarded (inspector-checked) so a re-run / partially-migrated DB is a no-op.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def _columns(table: str) -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {c['name'] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if 'duration_minutes' not in _columns('service_plans'):
        op.add_column(
            'service_plans',
            sa.Column('duration_minutes', sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    if 'duration_minutes' in _columns('service_plans'):
        op.drop_column('service_plans', 'duration_minutes')
