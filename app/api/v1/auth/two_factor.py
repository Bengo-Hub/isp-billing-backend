"""Two-Factor Authentication API endpoints."""

import hashlib
import io
import secrets
from base64 import b64encode
from datetime import datetime
from typing import Any, Dict, List

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.security import verify_password
from app.models.user import User
from app.models.user_settings import UserSettings

router = APIRouter(prefix="/2fa", tags=["Two-Factor Authentication"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TwoFactorSetupResponse(BaseModel):
    """Response for 2FA setup initiation."""
    secret: str
    qr_code: str  # base64 data URI
    otpauth_url: str


class TwoFactorVerifyRequest(BaseModel):
    """Request to verify TOTP code during setup."""
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class TwoFactorVerifyResponse(BaseModel):
    """Response after verifying 2FA setup."""
    success: bool
    recovery_codes: List[str]
    message: str


class TwoFactorDisableRequest(BaseModel):
    """Request to disable 2FA."""
    password: str = Field(..., min_length=1)


class TwoFactorChallengeRequest(BaseModel):
    """Request to verify TOTP during login."""
    temp_token: str = Field(..., min_length=1)
    code: str = Field(..., min_length=6, max_length=8)


class TwoFactorStatusResponse(BaseModel):
    """2FA status for current user."""
    enabled: bool
    method: str
    confirmed_at: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_recovery_code(code: str) -> str:
    """Hash a recovery code for storage."""
    return hashlib.sha256(code.encode()).hexdigest()


def _generate_recovery_codes(count: int = 8) -> List[str]:
    """Generate a set of human-readable recovery codes."""
    return [secrets.token_hex(4).upper() for _ in range(count)]


async def _get_or_create_settings(
    db: AsyncSession, user_id: int
) -> UserSettings:
    """Get existing user settings or create defaults."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
        await db.flush()
    return settings


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status", response_model=TwoFactorStatusResponse)
async def get_2fa_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current 2FA status for the authenticated user."""
    settings = await _get_or_create_settings(db, current_user.id)
    return TwoFactorStatusResponse(
        enabled=settings.two_factor_enabled,
        method=settings.two_factor_method,
        confirmed_at=(
            settings.two_factor_confirmed_at.isoformat()
            if settings.two_factor_confirmed_at
            else None
        ),
    )


@router.post("/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Initiate 2FA setup.

    Generates a TOTP secret and QR code.  The user must scan the QR code
    with an authenticator app then call POST /2fa/verify to confirm.
    """
    settings = await _get_or_create_settings(db, current_user.id)

    if settings.two_factor_enabled and settings.two_factor_confirmed_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-factor authentication is already enabled. Disable it first to reconfigure.",
        )

    # Generate new TOTP secret
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    otpauth_url = totp.provisioning_uri(
        name=current_user.email,
        issuer_name="ISP Billing",
    )

    # Generate QR code as data URI
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(otpauth_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = b64encode(buf.getvalue()).decode()

    # Store secret (unconfirmed – will be confirmed after verify)
    settings.totp_secret = secret
    settings.two_factor_enabled = False
    settings.two_factor_confirmed_at = None
    await db.commit()

    return TwoFactorSetupResponse(
        secret=secret,
        qr_code=f"data:image/png;base64,{qr_b64}",
        otpauth_url=otpauth_url,
    )


@router.post("/verify", response_model=TwoFactorVerifyResponse)
async def verify_2fa_setup(
    body: TwoFactorVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Verify the TOTP code to confirm 2FA setup.

    Returns recovery codes that the user **must** save securely.
    """
    settings = await _get_or_create_settings(db, current_user.id)

    if not settings.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No 2FA setup in progress. Call POST /2fa/setup first.",
        )

    totp = pyotp.TOTP(settings.totp_secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Please try again.",
        )

    # Generate recovery codes
    raw_codes = _generate_recovery_codes(8)
    hashed_codes = [
        {"hash": _hash_recovery_code(c), "used": False} for c in raw_codes
    ]

    # Confirm 2FA
    settings.two_factor_enabled = True
    settings.two_factor_confirmed_at = datetime.utcnow()
    settings.recovery_codes = hashed_codes
    await db.commit()

    return TwoFactorVerifyResponse(
        success=True,
        recovery_codes=raw_codes,
        message="Two-factor authentication has been enabled successfully.",
    )


@router.post("/disable")
async def disable_2fa(
    body: TwoFactorDisableRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Disable 2FA. Requires password confirmation."""
    if not verify_password(body.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password.",
        )

    settings = await _get_or_create_settings(db, current_user.id)

    settings.two_factor_enabled = False
    settings.totp_secret = None
    settings.recovery_codes = None
    settings.two_factor_confirmed_at = None
    await db.commit()

    return {"message": "Two-factor authentication has been disabled."}


@router.get("/recovery-codes")
async def get_recovery_codes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Regenerate recovery codes.

    Old codes are invalidated and new ones are issued.
    """
    settings = await _get_or_create_settings(db, current_user.id)

    if not settings.two_factor_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-factor authentication is not enabled.",
        )

    raw_codes = _generate_recovery_codes(8)
    hashed_codes = [
        {"hash": _hash_recovery_code(c), "used": False} for c in raw_codes
    ]
    settings.recovery_codes = hashed_codes
    await db.commit()

    return {
        "recovery_codes": raw_codes,
        "message": "New recovery codes generated. Previous codes are now invalid.",
    }


@router.post("/authenticate")
async def authenticate_2fa(
    body: TwoFactorChallengeRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Complete login by verifying TOTP or recovery code after initial auth.

    The temp_token is the short-lived token returned by /login when 2FA is required.
    """
    from app.core.security import verify_token, create_token_pair

    token_data = verify_token(body.temp_token, token_type="2fa_challenge")
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired challenge token.",
        )

    # Load user + settings
    result = await db.execute(
        select(User).where(User.id == token_data.user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )

    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    settings = settings_result.scalar_one_or_none()
    if not settings or not settings.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not configured for this account.",
        )

    code = body.code.strip()
    verified = False

    # Try TOTP first
    if len(code) == 6 and code.isdigit():
        totp = pyotp.TOTP(settings.totp_secret)
        verified = totp.verify(code, valid_window=1)

    # Try recovery code
    if not verified and settings.recovery_codes:
        code_hash = _hash_recovery_code(code)
        for rc in settings.recovery_codes:
            if rc["hash"] == code_hash and not rc.get("used"):
                rc["used"] = True
                verified = True
                # Persist used flag
                await db.flush()
                break

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid verification code.",
        )

    # Issue real tokens
    tokens = create_token_pair(
        user_id=user.id,
        username=user.username,
        role=user.role.value,
        organization_id=user.organization_id,
    )

    # Build user payload (same as login)
    from app.schemas.user import User as UserSchema

    user_payload = UserSchema.model_validate(user).model_dump()

    return {
        "data": {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "token_type": tokens["token_type"],
            "expires_in": 30 * 60,
            "user": user_payload,
        }
    }
