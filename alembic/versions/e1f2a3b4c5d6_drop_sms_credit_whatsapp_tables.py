"""drop SMS-credit / WhatsApp messaging + subscription tables

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-06-17 09:00:00.000000

Phase C1 cleanup. SMS / email / WhatsApp notification DELIVERY, all messaging
CREDITS and WhatsApp SUBSCRIPTIONS are centralized on notifications-api now.
The corresponding local models / endpoints were removed from the codebase, so
their orphaned tables (and the orphaned organizations.sms_sender_id column) are
dropped here.

Dropped tables (SMS-credit subsystem):
  * sms_credit_usage_stats, sms_transactions, sms_top_ups, sms_credit_alerts,
    sms_credit_accounts  (children first; CASCADE covers the FKs anyway)
  * phone_number_management
  * sms_gateway_configs
  * platform_sms_settings

Dropped tables (WhatsApp subsystem):
  * whatsapp_messages, whatsapp_subscription_payments,
    whatsapp_organization_subscriptions, whatsapp_subscription_packages
  * whatsapp_gateway_configs
  * platform_whatsapp_settings

Dropped column:
  * organizations.sms_sender_id

KEPT: the OrganizationSettings SMS/WhatsApp *message template* columns
(send_*_sms / *_sms / whatsapp_* / *_whatsapp) are intentionally NOT dropped —
they are per-tenant notification templates consumed by notifications-api, not
SMS-credit/subscription billing state.

Guarded: every drop is wrapped in an existence check (or uses IF EXISTS /
CASCADE) so a re-run, or a run against a DB where the objects were never
created, is a no-op rather than an error — matching the repo's
idempotent-migration convention.

Irreversible: this is a destructive cleanup of deprecated data whose ownership
moved to notifications-api. ``downgrade`` is intentionally a no-op (the
tables/column cannot be meaningfully restored).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e1f2a3b4c5d6'
down_revision = 'd0e1f2a3b4c5'
branch_labels = None
depends_on = None


# Reverse-dependency order (children before parents) for readability; CASCADE
# handles the real inter-table FKs regardless.
_DEPRECATED_TABLES = [
    # SMS-credit subsystem
    "sms_credit_usage_stats",
    "sms_transactions",
    "sms_top_ups",
    "sms_credit_alerts",
    "sms_credit_accounts",
    "phone_number_management",
    "sms_gateway_configs",
    "platform_sms_settings",
    # WhatsApp subsystem
    "whatsapp_messages",
    "whatsapp_subscription_payments",
    "whatsapp_organization_subscriptions",
    "whatsapp_subscription_packages",
    "whatsapp_gateway_configs",
    "platform_whatsapp_settings",
]


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(table)


def _columns(table: str) -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    # 1. Drop the orphaned organizations.sms_sender_id column (if present).
    if "sms_sender_id" in _columns("organizations"):
        op.drop_column("organizations", "sms_sender_id")

    # 2. Drop the deprecated tables (guarded; CASCADE clears dependent FKs).
    for table in _DEPRECATED_TABLES:
        if _has_table(table):
            op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')


def downgrade() -> None:
    # Intentional no-op: destructive cleanup of deprecated SMS-credit / WhatsApp
    # subsystems whose ownership moved to notifications-api. The tables/column
    # cannot be meaningfully recreated with their former data.
    pass
