"""add treasury_payment_intent_id on customer_purchases

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-15 12:00:00.000000

Phase 2 (ADDITIVE): when settings.use_treasury_payments is True, customer
(hotspot/PPPoE) payments are routed through the central treasury-api. This
stores the treasury payment_intent_id on the local CustomerPurchase snapshot so
the payment/status poller can verify the intent against treasury.

The column is nullable so existing direct-gateway purchases (the live, default
path) are unaffected. ``op.add_column`` is guarded with an inspector check so a
re-run on a partially-migrated DB is a no-op rather than an error (matching the
repo's idempotent-on-startup convention).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
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
    cols = _existing_columns('customer_purchases')

    if 'treasury_payment_intent_id' not in cols:
        op.add_column(
            'customer_purchases',
            sa.Column('treasury_payment_intent_id', sa.String(length=64), nullable=True),
        )
        # Indexed for the payment/status poller's intent lookup.
        if 'ix_customer_purchases_treasury_payment_intent_id' not in _existing_indexes('customer_purchases'):
            op.create_index(
                'ix_customer_purchases_treasury_payment_intent_id',
                'customer_purchases',
                ['treasury_payment_intent_id'],
                unique=False,
            )


def downgrade() -> None:
    cols = _existing_columns('customer_purchases')

    if 'treasury_payment_intent_id' in cols:
        if 'ix_customer_purchases_treasury_payment_intent_id' in _existing_indexes('customer_purchases'):
            op.drop_index(
                'ix_customer_purchases_treasury_payment_intent_id',
                table_name='customer_purchases',
            )
        op.drop_column('customer_purchases', 'treasury_payment_intent_id')
