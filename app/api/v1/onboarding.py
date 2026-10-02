"""
ISP Provider Onboarding API.

Multi-step signup flow for new ISP providers.
"""

import json
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status, BackgroundTasks
from pydantic import BaseModel, Field, EmailStr, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.redis import redis_client
from app.core.rate_limit import limit_credential_attempt
from app.core.security import get_password_hash, create_access_token
from app.models.organization import Organization, OrganizationType, OrganizationStatus
from app.models.user import User, UserRole, UserStatus

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


# =========================================================================
# Schemas
# =========================================================================

class EmailCheckRequest(BaseModel):
    """Schema for email check request."""

    email: EmailStr


class EmailCheckResponse(BaseModel):
    """Schema for email check response."""

    available: bool
    message: str


class VerificationCodeRequest(BaseModel):
    """Schema for sending verification code."""

    email: EmailStr


class VerificationCodeResponse(BaseModel):
    """Schema for verification code response."""

    success: bool
    message: str


class BusinessDetailsRequest(BaseModel):
    """Schema for business details."""

    email: EmailStr
    business_name: str = Field(..., min_length=2, max_length=200)
    business_type: OrganizationType
    phone: str = Field(..., pattern=r"^\+?[1-9]\d{1,14}$")
    country: str = Field(default="Kenya", max_length=100)
    city: Optional[str] = Field(None, max_length=100)


class SecuritySetupRequest(BaseModel):
    """Schema for security setup."""

    email: EmailStr
    admin_first_name: str = Field(..., min_length=1, max_length=100)
    admin_last_name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8)
    confirm_password: str

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v


class VerifyEmailRequest(BaseModel):
    """Schema for email verification."""

    email: EmailStr
    verification_code: str = Field(..., min_length=6, max_length=6)


class OnboardingCompleteResponse(BaseModel):
    """Schema for onboarding complete response."""

    success: bool
    message: str
    organization_id: Optional[int] = None
    organization_slug: Optional[str] = None
    access_token: Optional[str] = None
    token_type: str = "bearer"


class OnboardingStatusResponse(BaseModel):
    """Schema for onboarding status response."""

    email: str
    step: str  # email_verified, business_details, security_setup, complete
    business_name: Optional[str] = None
    business_type: Optional[str] = None


# =========================================================================
# Onboarding sessions live in Redis, so every backend replica sees the same
# signup in progress and a restart does not lose it. Before, they were a
# module-level dict: a code sent by one replica was unknown to the next.
# Structure: {verification_code, expires_at, step, verified, business_details,
# security_details}, one key per email, expiring an hour after the last step.
# =========================================================================

ONBOARDING_SESSION_TTL_SECONDS = 3600


def _session_key(email: str) -> str:
    return "isp:onboarding:" + email.strip().lower()


async def _redis():
    try:
        if not redis_client.redis:
            await redis_client.connect()
        return redis_client.redis
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Registration is temporarily unavailable. Please try again shortly.",
        ) from exc


async def load_session(email: str) -> Optional[dict]:
    """Return the onboarding session for email, or None."""
    try:
        raw = await (await _redis()).get(_session_key(email))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Registration is temporarily unavailable. Please try again shortly.",
        ) from exc
    if not raw:
        return None
    session = json.loads(raw)
    session["expires_at"] = datetime.fromisoformat(session["expires_at"])
    business = session.get("business_details")
    if business and business.get("business_type"):
        business["business_type"] = OrganizationType(business["business_type"])
    return session


async def save_session(email: str, session: dict) -> None:
    """Store the onboarding session for email (refreshing its expiry)."""
    data = dict(session)
    data["expires_at"] = session["expires_at"].isoformat()
    business = session.get("business_details")
    if business and business.get("business_type") is not None:
        data["business_details"] = dict(business)
        bt = business["business_type"]
        data["business_details"]["business_type"] = bt.value if hasattr(bt, "value") else bt
    try:
        await (await _redis()).set(
            _session_key(email), json.dumps(data), ex=ONBOARDING_SESSION_TTL_SECONDS
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Registration is temporarily unavailable. Please try again shortly.",
        ) from exc


async def delete_session(email: str) -> None:
    try:
        await (await _redis()).delete(_session_key(email))
    except Exception:
        pass  # expires on its own


def generate_verification_code() -> str:
    """Generate a 6-digit verification code."""
    return "".join([str(secrets.randbelow(10)) for _ in range(6)])


def get_default_trial_days() -> int:
    """Get default trial days from settings."""
    return getattr(settings, "default_trial_days", 14)


# =========================================================================
# Endpoints
# =========================================================================

@router.post("/check-email", response_model=EmailCheckResponse)
async def check_email_availability(
    data: EmailCheckRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Check if an email is available for registration.

    Step 1 of onboarding.
    """
    # Check if email exists in users table
    result = await db.execute(
        select(func.count(User.id)).where(User.email == data.email)
    )
    user_count = result.scalar()

    if user_count > 0:
        return EmailCheckResponse(
            available=False,
            message="This email is already registered. Please login instead."
        )

    # Check if email exists in organizations table
    result = await db.execute(
        select(func.count(Organization.id)).where(Organization.email == data.email)
    )
    org_count = result.scalar()

    if org_count > 0:
        return EmailCheckResponse(
            available=False,
            message="This email is already associated with an organization."
        )

    return EmailCheckResponse(
        available=True,
        message="Email is available for registration."
    )


@router.post("/send-verification", response_model=VerificationCodeResponse)
async def send_verification_code(
    request: Request,
    data: VerificationCodeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Send verification code to email.

    Step 2 of onboarding.
    """
    await limit_credential_attempt(request, "onboarding-send", data.email)
    # Check email availability first
    result = await db.execute(
        select(func.count(User.id)).where(User.email == data.email)
    )
    if result.scalar() > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered"
        )

    # Generate verification code
    code = generate_verification_code()
    expires_at = datetime.utcnow() + timedelta(minutes=15)

    # Store in session
    await save_session(data.email, {
        "verification_code": code,
        "expires_at": expires_at,
        "step": "verification_sent",
        "verified": False,
        "business_details": None,
        "security_details": None,
    })

    # TODO: Send email with verification code
    # For now, we'll log it (in production, use email service)
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Verification code for {data.email}: {code}")

    # In development, you might want to include the code in the response
    # Remove this in production!
    if getattr(settings, "debug", False):
        return VerificationCodeResponse(
            success=True,
            message=f"Verification code sent to {data.email}. [DEV: {code}]"
        )

    return VerificationCodeResponse(
        success=True,
        message=f"Verification code sent to {data.email}. Please check your inbox."
    )


@router.post("/verify-code")
async def verify_code(
    request: Request,
    data: VerifyEmailRequest,
):
    """
    Verify the email verification code.

    Step 3 of onboarding.
    """
    # Caps guesses at the 6-digit code per email, whatever the source address.
    await limit_credential_attempt(request, "onboarding-verify", data.email)
    session = await load_session(data.email)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verification code found. Please request a new code."
        )

    if datetime.utcnow() > session["expires_at"]:
        await delete_session(data.email)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired. Please request a new code."
        )

    if session["verification_code"] != data.verification_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code."
        )

    # Mark as verified
    session["verified"] = True
    session["step"] = "email_verified"
    await save_session(data.email, session)

    return {"success": True, "message": "Email verified successfully."}


@router.post("/business-details")
async def submit_business_details(
    data: BusinessDetailsRequest,
):
    """
    Submit business details.

    Step 4 of onboarding.
    """
    session = await load_session(data.email)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please start the registration process from the beginning."
        )

    if not session.get("verified"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please verify your email first."
        )

    # Store business details
    session["business_details"] = {
        "business_name": data.business_name,
        "business_type": data.business_type,
        "phone": data.phone,
        "country": data.country,
        "city": data.city,
    }
    session["step"] = "business_details"
    await save_session(data.email, session)

    return {"success": True, "message": "Business details saved."}


@router.post("/security-setup", response_model=OnboardingCompleteResponse)
async def complete_registration(
    data: SecuritySetupRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Complete registration with security setup.

    Final step of onboarding - creates organization and admin user.
    """
    session = await load_session(data.email)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please start the registration process from the beginning."
        )

    if not session.get("verified"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please verify your email first."
        )

    if not session.get("business_details"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please submit business details first."
        )

    business = session["business_details"]

    # Generate unique slug
    base_slug = business["business_name"].lower().replace(" ", "-")
    base_slug = "".join(c for c in base_slug if c.isalnum() or c == "-")

    # Check for existing slugs
    slug = base_slug
    counter = 1
    while True:
        result = await db.execute(
            select(func.count(Organization.id)).where(Organization.slug == slug)
        )
        if result.scalar() == 0:
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    # Tiers/subscriptions are owned by subscriptions-api now; the auto-subscribe
    # on tenant onboarding assigns the default plan + its 14-day trial. Locally we
    # only stamp a provisional trial window + sane default limits.
    trial_ends_at = datetime.utcnow() + timedelta(days=get_default_trial_days())

    # Create organization
    organization = Organization(
        name=business["business_name"],
        slug=slug,
        organization_type=business["business_type"],
        status=OrganizationStatus.TRIAL,
        email=data.email,
        phone=business["phone"],
        country=business.get("country", "Kenya"),
        city=business.get("city"),
        trial_ends_at=trial_ends_at,
        max_routers=5,
        max_customers=50,
        max_users=3,
        features={},
    )
    db.add(organization)
    await db.flush()  # Get organization ID

    # Create admin user
    admin_user = User(
        organization_id=organization.id,
        email=data.email,
        username=data.email.split("@")[0],
        hashed_password=get_password_hash(data.password),
        first_name=data.admin_first_name,
        last_name=data.admin_last_name,
        role=UserRole.ISP_ADMIN,
        status=UserStatus.ACTIVE,
        email_verified_at=datetime.utcnow(),
    )
    db.add(admin_user)

    await db.flush()

    # Create default organization settings
    from app.models.organization import OrganizationSettings
    org_settings = OrganizationSettings(
        organization_id=organization.id,
        enable_mikrotik_status_notifications=True,
        send_hotspot_payment_confirmation=True,
        hotspot_payment_confirmation_sms=(
            "Hello @username! You've successfully subscribed to @package_name. "
            "Username: @username, Password: @password, Expires: @expiry_date. Thank you!"
        ),
        send_pppoe_payment_confirmation=True,
        pppoe_payment_confirmation_sms=(
            "Hello @username! You've successfully subscribed to @package_name. "
            "Username: @username, Password: @password, Expires: @expiry_date. Thank you!"
        ),
        send_hotspot_expiry_notification=True,
        hotspot_expiry_notification_sms=(
            "Hello @username! Your @package_name subscription expired on @expiry_date. "
            "Renew now to continue enjoying our services."
        ),
        send_pppoe_expiry_notification=True,
        pppoe_expiry_notification_sms=(
            "Hello @username! Your @package_name subscription expired on @expiry_date. "
            "Renew now to continue enjoying our services."
        ),
        send_hotspot_expiry_reminder=True,
        hotspot_expiry_reminder_sms=(
            "Hello @username! Your @package_name subscription expires in @days_left days on @expiry_date. "
            "Renew now to avoid interruption."
        ),
        send_pppoe_expiry_reminder=True,
        pppoe_expiry_reminder_sms=(
            "Hello @username! Your @package_name subscription expires in @days_left days on @expiry_date. "
            "Renew now to avoid interruption."
        ),
        whatsapp_enabled=False,
    )
    db.add(org_settings)

    await db.commit()
    await db.refresh(organization)
    await db.refresh(admin_user)

    # Clean up session
    await delete_session(data.email)

    # Generate access token
    token = create_access_token(
        data={
            "sub": str(admin_user.id),
            "organization_id": organization.id,
            "role": admin_user.role.value,
        }
    )

    return OnboardingCompleteResponse(
        success=True,
        message=f"Welcome to Codevertex! Your {trial_days}-day free trial has started.",
        organization_id=organization.id,
        organization_slug=organization.slug,
        access_token=token,
    )


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    email: EmailStr,
):
    """
    Get the current onboarding status for an email.
    """
    session = await load_session(email)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No onboarding session found for this email."
        )

    business = session.get("business_details", {})

    return OnboardingStatusResponse(
        email=email,
        step=session.get("step", "unknown"),
        business_name=business.get("business_name") if business else None,
        business_type=business.get("business_type").value if business and business.get("business_type") else None,
    )


@router.post("/resend-code", response_model=VerificationCodeResponse)
async def resend_verification_code(
    request: Request,
    data: VerificationCodeRequest,
    background_tasks: BackgroundTasks,
):
    """
    Resend verification code.
    """
    await limit_credential_attempt(request, "onboarding-send", data.email)
    session = await load_session(data.email)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please start the registration process from the beginning."
        )

    # Generate new verification code
    code = generate_verification_code()
    expires_at = datetime.utcnow() + timedelta(minutes=15)

    session["verification_code"] = code
    session["expires_at"] = expires_at
    await save_session(data.email, session)

    # TODO: Send email with verification code
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"New verification code for {data.email}: {code}")

    if getattr(settings, "debug", False):
        return VerificationCodeResponse(
            success=True,
            message=f"New verification code sent to {data.email}. [DEV: {code}]"
        )

    return VerificationCodeResponse(
        success=True,
        message=f"New verification code sent to {data.email}."
    )
