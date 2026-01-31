"""Add platform SMS settings table

Revision ID: add_platform_sms_settings
Revises: 279ffe74982f
Create Date: 2026-01-30 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_platform_sms_settings'
down_revision = '279ffe74982f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'platform_sms_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cost_per_sms', sa.Numeric(precision=10, scale=4), nullable=False, server_default='0.50'),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='KES'),
        sa.Column('minimum_top_up_amount', sa.Numeric(precision=10, scale=2), nullable=False, server_default='100'),
        sa.Column('payment_method', sa.String(length=50), nullable=False, server_default='mpesa'),
        sa.Column('mpesa_paybill', sa.String(length=20), nullable=True),
        sa.Column('mpesa_till_number', sa.String(length=20), nullable=True),
        sa.Column('mpesa_account_name', sa.String(length=100), nullable=True),
        sa.Column('bank_account_number', sa.String(length=50), nullable=True),
        sa.Column('bank_name', sa.String(length=100), nullable=True),
        sa.Column('bank_branch', sa.String(length=100), nullable=True),
        sa.Column('paystack_subaccount_code', sa.String(length=100), nullable=True),
        sa.Column('sms_per_unit', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_platform_sms_settings_id'), 'platform_sms_settings', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_platform_sms_settings_id'), table_name='platform_sms_settings')
    op.drop_table('platform_sms_settings')
