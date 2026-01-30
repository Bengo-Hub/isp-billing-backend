"""merge_sms_settings_migration

Revision ID: 97cc278fcb46
Revises: add_platform_sms_settings, b8c3f7a2e9d1
Create Date: 2026-01-30 23:39:09.772675

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '97cc278fcb46'
down_revision = ('add_platform_sms_settings', 'b8c3f7a2e9d1')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
