"""Add 2FA TOTP columns to user_settings

Revision ID: a2f8c94d1e3b
Revises: 7f442b4e719a
Create Date: 2026-02-07 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a2f8c94d1e3b'
down_revision = '7f442b4e719a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add TOTP-based two-factor authentication columns to user_settings table.

    - totp_secret: Stores the encrypted TOTP secret for authenticator apps
    - recovery_codes: JSON array of hashed recovery codes
    - two_factor_confirmed_at: Timestamp when 2FA was fully verified/enabled
    """
    op.add_column(
        'user_settings',
        sa.Column('totp_secret', sa.String(length=255), nullable=True)
    )
    op.add_column(
        'user_settings',
        sa.Column('recovery_codes', sa.JSON(), nullable=True)
    )
    op.add_column(
        'user_settings',
        sa.Column('two_factor_confirmed_at', sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    """Remove 2FA TOTP columns from user_settings table."""
    op.drop_column('user_settings', 'two_factor_confirmed_at')
    op.drop_column('user_settings', 'recovery_codes')
    op.drop_column('user_settings', 'totp_secret')
