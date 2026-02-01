"""Add WhatsApp payment collection fields

Revision ID: 7f442b4e719a
Revises: 6e331a3d608f
Create Date: 2026-02-01 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '7f442b4e719a'
down_revision = '6e331a3d608f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add payment collection fields to platform_whatsapp_settings table.

    These fields allow platform admins to configure where ISP provider
    WhatsApp subscription payments should be collected (M-PESA, Bank, Paystack).
    """
    # Add payment collection fields
    op.add_column('platform_whatsapp_settings', sa.Column('minimum_subscription_months', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('platform_whatsapp_settings', sa.Column('payment_method', sa.String(length=50), nullable=False, server_default='paystack'))
    op.add_column('platform_whatsapp_settings', sa.Column('mpesa_paybill', sa.String(length=20), nullable=True))
    op.add_column('platform_whatsapp_settings', sa.Column('mpesa_till_number', sa.String(length=20), nullable=True))
    op.add_column('platform_whatsapp_settings', sa.Column('mpesa_account_name', sa.String(length=100), nullable=True))
    op.add_column('platform_whatsapp_settings', sa.Column('bank_account_number', sa.String(length=50), nullable=True))
    op.add_column('platform_whatsapp_settings', sa.Column('bank_name', sa.String(length=100), nullable=True))
    op.add_column('platform_whatsapp_settings', sa.Column('bank_branch', sa.String(length=100), nullable=True))
    op.add_column('platform_whatsapp_settings', sa.Column('bank_swift_code', sa.String(length=20), nullable=True))
    op.add_column('platform_whatsapp_settings', sa.Column('paystack_subaccount_code', sa.String(length=100), nullable=True))
    op.add_column('platform_whatsapp_settings', sa.Column('auto_renewal_enabled', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('platform_whatsapp_settings', sa.Column('auto_renewal_grace_days', sa.Integer(), nullable=False, server_default='3'))


def downgrade() -> None:
    """Remove payment collection fields from platform_whatsapp_settings table."""
    op.drop_column('platform_whatsapp_settings', 'auto_renewal_grace_days')
    op.drop_column('platform_whatsapp_settings', 'auto_renewal_enabled')
    op.drop_column('platform_whatsapp_settings', 'paystack_subaccount_code')
    op.drop_column('platform_whatsapp_settings', 'bank_swift_code')
    op.drop_column('platform_whatsapp_settings', 'bank_branch')
    op.drop_column('platform_whatsapp_settings', 'bank_name')
    op.drop_column('platform_whatsapp_settings', 'bank_account_number')
    op.drop_column('platform_whatsapp_settings', 'mpesa_account_name')
    op.drop_column('platform_whatsapp_settings', 'mpesa_till_number')
    op.drop_column('platform_whatsapp_settings', 'mpesa_paybill')
    op.drop_column('platform_whatsapp_settings', 'payment_method')
    op.drop_column('platform_whatsapp_settings', 'minimum_subscription_months')
