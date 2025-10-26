"""Middleware for auto-seeding demo and superuser accounts."""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.security import get_password_hash
from app.models.user import User, UserRole, UserStatus
from app.models.rbac import Role, SystemLicence, Permission, UserPermission
from app.services.rbac_service import RBACService
from sqlalchemy.orm import sessionmaker


class SeedMiddleware(BaseHTTPMiddleware):
    """Middleware to ensure demo and superuser accounts exist."""
    
    def __init__(self, app):
        super().__init__(app)
        self._seeded = False
    
    async def dispatch(self, request: Request, call_next):
        """Ensure seeding is done on first request."""
        if not self._seeded:
            await self._ensure_seeded()
            self._seeded = True
        
        response = await call_next(request)
        return response
    
    async def _ensure_seeded(self):
        """Ensure demo and superuser accounts exist."""
        # Create a session factory
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = SessionLocal()
        try:
            rbac_service = RBACService(db)
            
            # Initialize system roles and permissions
            print("Initializing RBAC system...")
            roles = rbac_service.initialize_system_roles_and_permissions()
            print(f"Created {len(roles)} system roles")
            
            # Ensure superuser account exists
            superuser = db.query(User).filter(User.username == "superuser").first()
            if not superuser:
                print("Creating superuser account...")
                superuser_role = roles["superuser"]
                superuser = User(
                    username="superuser",
                    email="superuser@codevertexitsolutions.com",
                    first_name="Super",
                    last_name="User",
                    company_name="Codevertex IT Solutions",
                    hashed_password=get_password_hash("superuser123"),
                    role=UserRole.SUPERUSER,
                    status=UserStatus.ACTIVE,
                    is_verified=True,
                    is_active=True
                )
                superuser.role_obj = superuser_role
                db.add(superuser)
                print("Superuser account created")
            else:
                # Ensure superuser has the correct role
                if not superuser.role_obj or superuser.role_obj.name != "superuser":
                    superuser.role_obj = roles["superuser"]
                    print("Superuser role updated")
            
            # Ensure demo admin account exists
            demo_admin = db.query(User).filter(User.username == "demo").first()
            if not demo_admin:
                print("Creating demo admin account...")
                admin_role = roles["admin"]
                demo_admin = User(
                    username="demo",
                    email="demo@codevertexitsolutions.com",
                    first_name="Demo",
                    last_name="Admin",
                    company_name="Demo ISP Company",
                    hashed_password=get_password_hash("demo123"),
                    role=UserRole.ADMIN,
                    status=UserStatus.ACTIVE,
                    is_verified=True,
                    is_active=True
                )
                demo_admin.role_obj = admin_role
                db.add(demo_admin)
                print("Demo admin account created")
            else:
                # Ensure demo admin has the correct role
                if not demo_admin.role_obj or demo_admin.role_obj.name != "admin":
                    demo_admin.role_obj = roles["admin"]
                    print("Demo admin role updated")
            
            # Ensure demo licence exists
            demo_licence = db.query(SystemLicence).filter(SystemLicence.licence_key == "DEMO-TRIAL-2024").first()
            if not demo_licence:
                print("Creating demo licence...")
                demo_licence = rbac_service.create_system_licence(
                    licence_key="DEMO-TRIAL-2024",
                    organization_name="Demo ISP Company",
                    contact_email="demo@codevertexitsolutions.com",
                    contact_phone="+254 700 000 000",
                    licence_type="trial",
                    trial_days=14,
                    max_users=100,
                    max_routers=20
                )
                # Activate the trial
                rbac_service.activate_licence_trial(demo_licence.id)
                print("Demo licence created and activated")
            
            db.commit()
            print("RBAC system initialization completed successfully")
            
        except Exception as e:
            print(f"Error seeding accounts: {e}")
            import traceback
            traceback.print_exc()
            db.rollback()
        finally:
            db.close()
