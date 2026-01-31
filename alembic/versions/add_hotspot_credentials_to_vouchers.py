"""Add hotspot credentials to voucher_codes table.

Revision ID: d0e5f9a4b3c6
Revises: c9d4e8f3a1b2
Create Date: 2026-01-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd0e5f9a4b3c6'
down_revision = 'c9d4e8f3a1b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add hotspot credentials fields to voucher_codes
    # These are auto-generated when a customer purchases a package
    # Username format: PREFIX + INCREMENTAL_NUMBER (e.g., C029, H0001)
    # Password format: Random 3-digit number (e.g., 865, 123)

    op.add_column(
        'voucher_codes',
        sa.Column('hotspot_username', sa.String(50), nullable=True)
    )

    op.add_column(
        'voucher_codes',
        sa.Column('hotspot_password', sa.String(20), nullable=True)
    )

    # Create index for hotspot_username for faster lookups
    # Using if_not_exists to handle cases where partial migration ran
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_voucher_codes_hotspot_username
        ON voucher_codes (hotspot_username)
    """)


def downgrade() -> None:
    op.drop_index('ix_voucher_codes_hotspot_username', table_name='voucher_codes')
    op.drop_column('voucher_codes', 'hotspot_password')
    op.drop_column('voucher_codes', 'hotspot_username')
