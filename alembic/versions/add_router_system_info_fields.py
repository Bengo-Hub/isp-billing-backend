"""Add router system info fields

Revision ID: add_router_system_info
Revises: add_winbox_remote_access
Create Date: 2026-01-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'add_router_system_info'
down_revision: Union[str, None] = 'd5e6f7g8h9i0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column already exists in the table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """Add system resource fields to routers table."""
    # Add routeros_version column
    if not column_exists('routers', 'routeros_version'):
        op.add_column('routers', sa.Column('routeros_version', sa.String(50), nullable=True))

    # Add board_name column
    if not column_exists('routers', 'board_name'):
        op.add_column('routers', sa.Column('board_name', sa.String(100), nullable=True))

    # Add architecture column
    if not column_exists('routers', 'architecture'):
        op.add_column('routers', sa.Column('architecture', sa.String(50), nullable=True))

    # Add cpu_count column
    if not column_exists('routers', 'cpu_count'):
        op.add_column('routers', sa.Column('cpu_count', sa.Integer(), nullable=True))

    # Add cpu_frequency column
    if not column_exists('routers', 'cpu_frequency'):
        op.add_column('routers', sa.Column('cpu_frequency', sa.Integer(), nullable=True))

    # Add cpu_load column
    if not column_exists('routers', 'cpu_load'):
        op.add_column('routers', sa.Column('cpu_load', sa.Integer(), nullable=True))

    # Add total_memory column (BigInteger for bytes)
    if not column_exists('routers', 'total_memory'):
        op.add_column('routers', sa.Column('total_memory', sa.BigInteger(), nullable=True))

    # Add free_memory column (BigInteger for bytes)
    if not column_exists('routers', 'free_memory'):
        op.add_column('routers', sa.Column('free_memory', sa.BigInteger(), nullable=True))

    # Add total_hdd_space column (BigInteger for bytes)
    if not column_exists('routers', 'total_hdd_space'):
        op.add_column('routers', sa.Column('total_hdd_space', sa.BigInteger(), nullable=True))

    # Add free_hdd_space column (BigInteger for bytes)
    if not column_exists('routers', 'free_hdd_space'):
        op.add_column('routers', sa.Column('free_hdd_space', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    """Remove system resource fields from routers table."""
    # Remove columns in reverse order
    columns_to_remove = [
        'free_hdd_space',
        'total_hdd_space',
        'free_memory',
        'total_memory',
        'cpu_load',
        'cpu_frequency',
        'cpu_count',
        'architecture',
        'board_name',
        'routeros_version',
    ]

    for column_name in columns_to_remove:
        if column_exists('routers', column_name):
            op.drop_column('routers', column_name)
