"""add_organization_id_to_sms_credit_accounts

Revision ID: c998761fc519
Revises: 97cc278fcb46
Create Date: 2026-01-30 23:52:44.793002

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c998761fc519'
down_revision = '97cc278fcb46'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add organization_id column to sms_credit_accounts
    op.add_column(
        'sms_credit_accounts',
        sa.Column('organization_id', sa.Integer(), nullable=True)
    )
    # Add foreign key constraint
    op.create_foreign_key(
        'fk_sms_credit_accounts_organization_id',
        'sms_credit_accounts',
        'organizations',
        ['organization_id'],
        ['id']
    )
    # Add index for faster lookups
    op.create_index(
        'ix_sms_credit_accounts_organization_id',
        'sms_credit_accounts',
        ['organization_id']
    )


def downgrade() -> None:
    op.drop_index('ix_sms_credit_accounts_organization_id', table_name='sms_credit_accounts')
    op.drop_constraint('fk_sms_credit_accounts_organization_id', 'sms_credit_accounts', type_='foreignkey')
    op.drop_column('sms_credit_accounts', 'organization_id')
