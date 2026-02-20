"""add router_commands table and agent fields to routers

Revision ID: a1b2c3d4e5f6
Revises: 70e401e50c75
Create Date: 2026-02-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '70e401e50c75'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Router Commands table ---
    op.create_table(
        'router_commands',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('router_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('params', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('priority', sa.Integer(), nullable=True, server_default='5'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('result_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.Column('source_id', sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(['router_id'], ['routers.id'], name=op.f('fk_router_commands_router_id_routers')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_router_commands')),
    )
    op.create_index(op.f('ix_router_commands_router_id'), 'router_commands', ['router_id'], unique=False)
    op.create_index(op.f('ix_router_commands_status'), 'router_commands', ['status'], unique=False)
    op.create_index(
        'ix_router_commands_pending_lookup',
        'router_commands',
        ['router_id', 'status', 'priority', 'created_at'],
        unique=False,
    )

    # --- Agent fields on routers table ---
    op.add_column('routers', sa.Column('agent_token', sa.String(length=255), nullable=True))
    op.add_column('routers', sa.Column('agent_token_plain', sa.Text(), nullable=True))
    op.add_column('routers', sa.Column('agent_installed', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('routers', sa.Column('agent_poll_interval', sa.Integer(), nullable=False, server_default='30'))
    op.add_column('routers', sa.Column('last_poll_at', sa.DateTime(), nullable=True))
    op.add_column('routers', sa.Column('agent_version', sa.String(length=20), nullable=True))


def downgrade() -> None:
    # --- Remove agent fields from routers ---
    op.drop_column('routers', 'agent_version')
    op.drop_column('routers', 'last_poll_at')
    op.drop_column('routers', 'agent_poll_interval')
    op.drop_column('routers', 'agent_installed')
    op.drop_column('routers', 'agent_token_plain')
    op.drop_column('routers', 'agent_token')

    # --- Drop router_commands table ---
    op.drop_index('ix_router_commands_pending_lookup', table_name='router_commands')
    op.drop_index(op.f('ix_router_commands_status'), table_name='router_commands')
    op.drop_index(op.f('ix_router_commands_router_id'), table_name='router_commands')
    op.drop_table('router_commands')
