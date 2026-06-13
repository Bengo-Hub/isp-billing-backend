"""add router_backups table + active-users telemetry columns on routers

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-14 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Agent-reported active user list (NAT-safe live data) on routers ---
    op.add_column('routers', sa.Column('active_users_json', sa.Text(), nullable=True))
    op.add_column('routers', sa.Column('active_users_at', sa.DateTime(), nullable=True))

    # --- Router backup history table ---
    op.create_table(
        'router_backups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('router_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('backup_type', sa.String(length=20), nullable=False, server_default='binary'),
        sa.Column('command_id', sa.String(length=36), nullable=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('requested_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['router_id'], ['routers.id'], name=op.f('fk_router_backups_router_id_routers')),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_router_backups_requested_by_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_router_backups')),
    )
    op.create_index(op.f('ix_router_backups_router_id'), 'router_backups', ['router_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_router_backups_router_id'), table_name='router_backups')
    op.drop_table('router_backups')
    op.drop_column('routers', 'active_users_at')
    op.drop_column('routers', 'active_users_json')
