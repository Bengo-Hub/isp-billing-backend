"""Add RBAC tables

Revision ID: add_rbac_tables
Revises: 99d8de282dcb
Create Date: 2024-01-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_rbac_tables'
down_revision = '99d8de282dcb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create roles table
    op.create_table('roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_system_role', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_roles_id'), 'roles', ['id'], unique=False)
    op.create_index(op.f('ix_roles_name'), 'roles', ['name'], unique=True)

    # Create permissions table
    op.create_table('permissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('module', sa.Enum('DASHBOARD', 'USERS', 'PACKAGES', 'ROUTERS', 'PROVISIONING', 'PAYMENTS', 'SMS', 'SETTINGS', 'REPORTS', 'NOTIFICATIONS', 'SYSTEM_CONFIG', 'LICENCE_MANAGEMENT', 'AUDIT_LOGS', 'BACKUP_RESTORE', name='permissionmodule'), nullable=False),
        sa.Column('action', sa.Enum('CREATE', 'READ', 'UPDATE', 'DELETE', 'MANAGE', name='permissionaction'), nullable=False),
        sa.Column('resource', sa.String(length=100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('module', 'action', 'resource', name='uq_permission_module_action_resource')
    )
    op.create_index(op.f('ix_permissions_id'), 'permissions', ['id'], unique=False)
    op.create_index(op.f('ix_permissions_module'), 'permissions', ['module'], unique=False)
    op.create_index(op.f('ix_permissions_action'), 'permissions', ['action'], unique=False)

    # Create role_permissions association table
    op.create_table('role_permissions',
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.Column('permission_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
        sa.PrimaryKeyConstraint('role_id', 'permission_id')
    )

    # Create user_permissions table
    op.create_table('user_permissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('permission_id', sa.Integer(), nullable=False),
        sa.Column('is_granted', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'permission_id', name='uq_user_permission')
    )
    op.create_index(op.f('ix_user_permissions_id'), 'user_permissions', ['id'], unique=False)

    # Create system_licences table
    op.create_table('system_licences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('licence_key', sa.String(length=255), nullable=False),
        sa.Column('organization_name', sa.String(length=200), nullable=False),
        sa.Column('contact_email', sa.String(length=100), nullable=False),
        sa.Column('contact_phone', sa.String(length=20), nullable=True),
        sa.Column('licence_type', sa.String(length=50), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('max_users', sa.Integer(), nullable=False),
        sa.Column('max_routers', sa.Integer(), nullable=False),
        sa.Column('trial_days', sa.Integer(), nullable=False),
        sa.Column('trial_started_at', sa.DateTime(), nullable=True),
        sa.Column('trial_expires_at', sa.DateTime(), nullable=True),
        sa.Column('subscription_started_at', sa.DateTime(), nullable=True),
        sa.Column('subscription_expires_at', sa.DateTime(), nullable=True),
        sa.Column('auto_renew', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_system_licences_id'), 'system_licences', ['id'], unique=False)
    op.create_index(op.f('ix_system_licences_licence_key'), 'system_licences', ['licence_key'], unique=True)

    # Add company_name column to users table
    op.add_column('users', sa.Column('company_name', sa.String(length=200), nullable=True))

    # Add role_id foreign key to users table
    op.add_column('users', sa.Column('role_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_users_role_id', 'users', 'roles', ['role_id'], ['id'])

    # Update user role enum to include superuser
    op.execute("ALTER TYPE userrole RENAME TO userrole_old")
    op.execute("CREATE TYPE userrole AS ENUM ('superuser', 'admin', 'technician', 'customer')")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::text::userrole")
    op.execute("DROP TYPE userrole_old")


def downgrade() -> None:
    # Remove foreign key and role_id column from users
    op.drop_constraint('fk_users_role_id', 'users', type_='foreignkey')
    op.drop_column('users', 'role_id')

    # Remove company_name column from users
    op.drop_column('users', 'company_name')

    # Revert user role enum
    op.execute("ALTER TYPE userrole RENAME TO userrole_old")
    op.execute("CREATE TYPE userrole AS ENUM ('admin', 'technician', 'customer')")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::text::userrole")
    op.execute("DROP TYPE userrole_old")

    # Drop tables
    op.drop_table('system_licences')
    op.drop_table('user_permissions')
    op.drop_table('role_permissions')
    op.drop_table('permissions')
    op.drop_table('roles')
