"""API v1 package.

This module organizes all API routes into logical groups:

1. Authentication
   - /auth - Authentication endpoints

2. User Management
   - /users - User management
   - /rbac - Role-based access control

3. Network Management
   - /routers - Router CRUD and operations
   - /provisioning - Device provisioning
   - /gateways - Gateway management

4. Business Operations
   - /plans - Service plans
   - /subscriptions - User subscriptions
   - /billing - Billing and payments

5. Administration
   - /admin - System administration
   - /licence - Licence management
   - /sms-credit - SMS credit management
   - /config - Configuration

6. Support & Analytics
   - /notifications - Notifications
   - /reports - Reports and analytics
   - /ui - User interface data

7. External Integrations
   - /mpesa - M-PESA integration

8. Platform Management (Platform Owner Only)
   - /platform/organizations - ISP provider management
   - /platform/billing - Platform billing and invoices
   - /platform/analytics - Platform-wide analytics
   - /platform/tiers - Subscription tier management

9. Customer Portals
   - /portal/hotspot - Hotspot customer portal
   - /portal/pppoe - PPPoE customer portal

10. Tenant Management (ISP Admin)
    - /tenant/payment-gateways - Payment gateway configuration
    - /tenant/settings - Organization settings

11. ISP Provider Onboarding
    - /onboarding - Multi-step signup flow
"""

from fastapi import APIRouter

# Import from organized folders
from .auth import router as auth_router
from .users import router as users_router
from .network import router as network_router
from .business import router as business_router
from .admin import router as admin_router
from .support import router as support_router
from .communications import router as communications_router
from .integrations import router as integrations_router
from .provisioning import router as provisioning_router
from .platform import router as platform_router
from .portal import router as portal_router
from .tenant import router as tenant_router
from .onboarding import router as onboarding_router
from .payments import router as payments_router

api_router = APIRouter()

# =============================================================================
# 1. Authentication
# =============================================================================
api_router.include_router(
    auth_router,
    prefix="/auth",
    tags=["Authentication"],
)

# =============================================================================
# 2. User Management
# =============================================================================
api_router.include_router(users_router)

# =============================================================================
# 3. Network Management
# =============================================================================
api_router.include_router(network_router)
api_router.include_router(
    provisioning_router,
    prefix="/provisioning",
    tags=["Device Provisioning"],
)

# =============================================================================
# 4. Business Operations
# =============================================================================
api_router.include_router(business_router)

# =============================================================================
# 5. Administration
# =============================================================================
api_router.include_router(admin_router)

# =============================================================================
# 6. Support & Analytics
# =============================================================================
api_router.include_router(support_router)

# =============================================================================
# 6.5. Communications
# =============================================================================
api_router.include_router(communications_router)

# =============================================================================
# 7. External Integrations
# =============================================================================
api_router.include_router(integrations_router)

# =============================================================================
# 8. Platform Management (Platform Owner Only)
# =============================================================================
api_router.include_router(platform_router)

# =============================================================================
# 9. Customer Portals
# =============================================================================
api_router.include_router(portal_router)

# =============================================================================
# 10. Tenant-specific Management (ISP Admin)
# =============================================================================
api_router.include_router(tenant_router)

# =============================================================================
# 11. ISP Provider Onboarding
# =============================================================================
api_router.include_router(onboarding_router)

# =============================================================================
# 12. Public Payment Endpoints (No Auth Required)
# =============================================================================
api_router.include_router(payments_router)
