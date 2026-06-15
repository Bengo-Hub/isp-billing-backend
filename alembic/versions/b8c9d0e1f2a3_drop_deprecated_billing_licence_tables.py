"""drop deprecated payment-gateway / licence / platform-billing tables

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-15 17:30:00.000000

Phase 2/3 cleanup. These subsystems were decentralised to the microservice
ecosystem and their local models/endpoints removed from the codebase:

  * payment_gateway_configs  -> per-tenant gateway creds now live in treasury-api
                                (customer/tenant payments route through treasury).
  * licences (+ licence_payments / licence_usage_logs / licence_features /
    licence_alerts) -> the local platform->ISP licence model is retired; ISP
    plan/entitlement gating is owned by subscriptions-api (`sub_*` JWT claims).
  * platform_subscription_tiers / platform_invoices / platform_payments ->
    ISP-provider subscriptions + invoicing are owned by subscriptions-api +
    treasury (ISP_* plans with treasury auto-invoicing).
  * organizations.subscription_tier_id (+ its FK) -> tier ownership moved out.

KEPT (still live domain): earnings_records, payment_transactions,
manual_payment_records, payout_configs, payout_records, and the unrelated
``system_licences`` table (app-level SystemLicence, not the ISP licence).

Guarded: every drop is wrapped in an existence check (or uses IF EXISTS /
CASCADE) so a re-run, or a run against a DB where the objects were never
created, is a no-op rather than an error — matching the repo's
idempotent-migration convention. CASCADE handles the inter-table FKs
(e.g. licence_* -> licences, platform_payments -> platform_invoices).

Irreversible: this is a destructive cleanup of deprecated data. ``downgrade``
is intentionally a no-op (the tables/column cannot be meaningfully restored;
the owning data now lives in treasury-api / subscriptions-api).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


# Order matters only for readability; CASCADE handles real dependencies.
_DEPRECATED_TABLES = [
    # licence subsystem (children first for clarity; CASCADE covers it anyway)
    "licence_alerts",
    "licence_features",
    "licence_usage_logs",
    "licence_payments",
    "licences",
    # platform -> ISP-provider subscription/invoicing subsystem
    "platform_payments",
    "platform_invoices",
    "platform_subscription_tiers",
    # local payment-gateway credential store
    "payment_gateway_configs",
]


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(table)


def _columns(table: str) -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    # 1. Drop the organizations.subscription_tier_id FK + column (if present).
    #    Dropping the constraint explicitly first keeps the change clean even on
    #    backends/older constraint names; the column drop is inspector-guarded.
    op.execute(
        "ALTER TABLE organizations DROP CONSTRAINT IF EXISTS "
        "fk_organizations_subscription_tier_id_platform_subscription_tiers"
    )
    if "subscription_tier_id" in _columns("organizations"):
        op.drop_column("organizations", "subscription_tier_id")

    # 2. Drop the deprecated tables (guarded; CASCADE clears dependent FKs).
    for table in _DEPRECATED_TABLES:
        if _has_table(table):
            op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')


def downgrade() -> None:
    # Intentional no-op: destructive cleanup of deprecated subsystems whose data
    # now lives in treasury-api / subscriptions-api. The tables/column cannot be
    # meaningfully recreated with their former data.
    pass
