"""Seed roles and permissions for RBAC (moved to scripts/seeds).
This file is a copy of the original seed_rbac.py; keep logic unchanged.
"""

# --- original content preserved ---

import asyncio
from datetime import datetime
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.rbac import Role, Permission, PermissionModule, PermissionAction


def _ensure_role(db: AsyncSession, name: str, description: str = "", is_system: bool = True) -> Role:
    role = db.query(Role).filter(Role.name == name).one_or_none()
    if role:
        return role
    role = Role(name=name, description=description, is_system_role=is_system)
    db.add(role)
    db.flush()
    return role


def _ensure_permission(db: AsyncSession, module: PermissionModule, action: PermissionAction, resource: str = None, description: str = None) -> Permission:
    perm = db.query(Permission).filter(
        Permission.module == module,
        Permission.action == action,
        Permission.resource == resource,
    ).one_or_none()
    if perm:
        return perm
    perm = Permission(module=module, action=action, resource=resource, description=description)
    db.add(perm)
    db.flush()
    return perm


async def seed_rbac(clear_existing: bool = False) -> List[Role]:
    """Seed basic roles and permissions."""
    async with AsyncSessionLocal() as db:
        # Use sync-style session within async context via run_sync
        def _work(sess):
            # Optionally clear existing roles/permissions
            if clear_existing:
                sess.query(Role).delete()
                sess.query(Permission).delete()
                sess.commit()

            # Create roles
            super_role = _ensure_role(sess, "SUPERUSER", "Platform superuser - full access")
            admin_role = _ensure_role(sess, "ADMIN", "ISP admin - tenant-level full access")
            tech_role = _ensure_role(sess, "TECHNICIAN", "Technician - limited operational access")
            customer_role = _ensure_role(sess, "CUSTOMER", "Customer - end-user access")

            # Comprehensive permission set to mirror frontend MODULE_PERMISSIONS
            module_actions = {
                PermissionModule.DASHBOARD: [PermissionAction.READ],

                PermissionModule.USERS: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE],
                PermissionModule.CUSTOMERS: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE],
                PermissionModule.PACKAGES: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE],
                PermissionModule.ROUTERS: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE],
                PermissionModule.PROVISIONING: [PermissionAction.MANAGE],
                PermissionModule.PAYMENTS: [PermissionAction.READ, PermissionAction.MANAGE],
                PermissionModule.PAYMENT_GATEWAYS: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE],
                PermissionModule.SMS: [PermissionAction.READ, PermissionAction.MANAGE],
                PermissionModule.VOUCHERS: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE],
                PermissionModule.SETTINGS: [PermissionAction.READ, PermissionAction.UPDATE],
                PermissionModule.REPORTS: [PermissionAction.READ, PermissionAction.MANAGE],
                PermissionModule.NOTIFICATIONS: [PermissionAction.READ, PermissionAction.MANAGE],
                PermissionModule.SUPPORT: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE],

                PermissionModule.BILLING: [PermissionAction.READ, PermissionAction.MANAGE],
                PermissionModule.SUBSCRIPTIONS: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE],
                PermissionModule.ANALYTICS: [PermissionAction.READ],
                PermissionModule.BRANDING: [PermissionAction.READ, PermissionAction.UPDATE],
                PermissionModule.AUDIT_LOGS: [PermissionAction.READ, PermissionAction.MANAGE],
                PermissionModule.BACKUP_RESTORE: [PermissionAction.MANAGE],

                # Platform-level modules (superuser only by default)
                PermissionModule.PLATFORM_ORGANIZATIONS: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE],
                PermissionModule.PLATFORM_BILLING: [PermissionAction.READ, PermissionAction.MANAGE],
                PermissionModule.PLATFORM_ANALYTICS: [PermissionAction.READ],
                PermissionModule.PLATFORM_CONFIG: [PermissionAction.MANAGE],
                PermissionModule.PLATFORM_TIERS: [PermissionAction.MANAGE],

                PermissionModule.PLATFORM_INTEGRATIONS: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE],
                PermissionModule.PLATFORM_INTEGRATIONS_SECRETS: [PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.MANAGE],
                PermissionModule.PLATFORM_INTEGRATIONS_URLS: [PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.MANAGE],
                PermissionModule.PLATFORM_PAYMENT_GATEWAYS: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE],
                PermissionModule.PLATFORM_SMS_GATEWAYS: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE],
                PermissionModule.PLATFORM_EMAIL_GATEWAYS: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE, PermissionAction.DELETE, PermissionAction.MANAGE],

                # Tenant-specific configs (ISP Admin)
                PermissionModule.TENANT_PAYMENT_CONFIG: [PermissionAction.READ, PermissionAction.UPDATE],
                PermissionModule.TENANT_SMS_CONFIG: [PermissionAction.READ, PermissionAction.UPDATE],
                PermissionModule.TENANT_PAYOUT_CONFIG: [PermissionAction.CREATE, PermissionAction.READ, PermissionAction.UPDATE],

                # Customer portal
                PermissionModule.CUSTOMER_DASHBOARD: [PermissionAction.READ],
                PermissionModule.CUSTOMER_PACKAGES: [PermissionAction.READ],
                PermissionModule.CUSTOMER_PAYMENTS: [PermissionAction.READ],
                PermissionModule.CUSTOMER_USAGE: [PermissionAction.READ],
                PermissionModule.CUSTOMER_PROFILE: [PermissionAction.READ, PermissionAction.UPDATE],
            }

            # Create Permission records for all module/action combos
            created_perms = []
            for module, actions in module_actions.items():
                for action in actions:
                    created_perms.append(_ensure_permission(sess, module, action))

            # Helper to fetch created permission by module/action
            def _find_perm(mod, act):
                for p in created_perms:
                    if p.module == mod and p.action == act:
                        return p
                return None

            # Assign permissions to roles (superuser gets all)
            super_role.permissions = list({*super_role.permissions, *created_perms})

            # Admin gets tenant-level management permissions (exclude platform-only modules)
            admin_modules = [
                PermissionModule.DASHBOARD,
                PermissionModule.USERS,
                PermissionModule.CUSTOMERS,
                PermissionModule.PACKAGES,
                PermissionModule.ROUTERS,
                PermissionModule.PROVISIONING,
                PermissionModule.PAYMENTS,
                PermissionModule.PAYMENT_GATEWAYS,
                PermissionModule.SMS,
                PermissionModule.VOUCHERS,
                PermissionModule.SETTINGS,
                PermissionModule.REPORTS,
                PermissionModule.NOTIFICATIONS,
                PermissionModule.SUPPORT,
                PermissionModule.BILLING,
                PermissionModule.SUBSCRIPTIONS,
                PermissionModule.ANALYTICS,
                PermissionModule.BRANDING,
                PermissionModule.AUDIT_LOGS,
                PermissionModule.TENANT_PAYMENT_CONFIG,
                PermissionModule.TENANT_SMS_CONFIG,
                PermissionModule.TENANT_PAYOUT_CONFIG,
            ]

            admin_perms = [p for p in created_perms if p.module in admin_modules]
            admin_role.permissions = list({*admin_role.permissions, *admin_perms})

            # Technician gets operational permissions
            tech_modules = [
                PermissionModule.DASHBOARD,
                PermissionModule.USERS,
                PermissionModule.CUSTOMERS,
                PermissionModule.PACKAGES,
                PermissionModule.ROUTERS,
                PermissionModule.PROVISIONING,
                PermissionModule.PAYMENTS,
                PermissionModule.SMS,
                PermissionModule.VOUCHERS,
                PermissionModule.NOTIFICATIONS,
                PermissionModule.SUPPORT,
                PermissionModule.SUBSCRIPTIONS,
            ]
            tech_perms = [p for p in created_perms if p.module in tech_modules]
            tech_role.permissions = list({*tech_role.permissions, *tech_perms})

            # Customer gets only customer-portal permissions
            customer_modules = [
                PermissionModule.CUSTOMER_DASHBOARD,
                PermissionModule.CUSTOMER_PACKAGES,
                PermissionModule.CUSTOMER_PAYMENTS,
                PermissionModule.CUSTOMER_USAGE,
                PermissionModule.CUSTOMER_PROFILE,
                PermissionModule.NOTIFICATIONS,
            ]
            customer_perms = [p for p in created_perms if p.module in customer_modules]
            customer_role.permissions = list({*customer_role.permissions, *customer_perms})

            sess.commit()
            return [super_role, admin_role, tech_role, customer_role]

        roles = await db.run_sync(_work)
        return roles


if __name__ == "__main__":
    asyncio.run(seed_rbac(clear_existing=True))