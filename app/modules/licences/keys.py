"""Licence key generation and validation operations.

This module handles licence key generation, validation, and related operations,
separated from the main licence service for maintainability.
"""

import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.licence import Licence, LicenceType
from app.core.logging import get_logger

logger = get_logger(__name__)


class KeyOperations:
    """Licence key generation and validation operations."""

    # Key format prefixes by licence type
    KEY_PREFIXES = {
        LicenceType.TRIAL: "TRL",
        LicenceType.BASIC: "BSC",
        LicenceType.PROFESSIONAL: "PRO",
        LicenceType.ENTERPRISE: "ENT",
        LicenceType.CUSTOM: "CST",
    }

    # Default validity periods by licence type (in days)
    VALIDITY_PERIODS = {
        LicenceType.TRIAL: 14,
        LicenceType.BASIC: 30,
        LicenceType.PROFESSIONAL: 365,
        LicenceType.ENTERPRISE: 365,
        LicenceType.CUSTOM: 3650,  # ~10 years
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    def generate_key(self, licence_type: LicenceType) -> str:
        """Generate a unique licence key.

        Format: PREFIX-XXXX-XXXX-XXXX-XXXX
        Where PREFIX is based on licence type and X is alphanumeric.
        """
        prefix = self.KEY_PREFIXES.get(licence_type, "LIC")

        # Generate 4 groups of 4 characters
        chars = string.ascii_uppercase + string.digits
        groups = [
            "".join(secrets.choice(chars) for _ in range(4))
            for _ in range(4)
        ]

        return f"{prefix}-{'-'.join(groups)}"

    async def key_exists(self, licence_key: str) -> bool:
        """Check if a licence key already exists."""
        result = await self.db.execute(
            select(Licence).where(Licence.licence_key == licence_key)
        )
        return result.scalar_one_or_none() is not None

    async def generate_unique_key(self, licence_type: LicenceType, max_attempts: int = 10) -> str:
        """Generate a unique licence key, retrying if collision occurs."""
        for _ in range(max_attempts):
            key = self.generate_key(licence_type)
            if not await self.key_exists(key):
                return key

        # Fallback: add timestamp suffix
        key = self.generate_key(licence_type)
        timestamp_suffix = datetime.utcnow().strftime("%H%M%S")
        return f"{key}-{timestamp_suffix}"

    def get_default_validity(self, licence_type: LicenceType) -> timedelta:
        """Get the default validity period for a licence type."""
        days = self.VALIDITY_PERIODS.get(licence_type, 30)
        return timedelta(days=days)

    def calculate_expiry_date(
        self,
        licence_type: LicenceType,
        start_date: Optional[datetime] = None,
    ) -> datetime:
        """Calculate the expiry date for a licence."""
        start = start_date or datetime.utcnow()
        validity = self.get_default_validity(licence_type)
        return start + validity

    def validate_key_format(self, licence_key: str) -> bool:
        """Validate licence key format."""
        if not licence_key:
            return False

        parts = licence_key.split("-")
        if len(parts) != 5:
            return False

        # Check prefix
        prefix = parts[0]
        valid_prefixes = list(self.KEY_PREFIXES.values()) + ["LIC"]
        if prefix not in valid_prefixes:
            return False

        # Check remaining parts are 4 alphanumeric characters
        for part in parts[1:]:
            if len(part) != 4:
                return False
            if not part.isalnum():
                return False

        return True

    def extract_licence_type_from_key(self, licence_key: str) -> Optional[LicenceType]:
        """Extract licence type from key prefix."""
        if not licence_key:
            return None

        prefix = licence_key.split("-")[0] if "-" in licence_key else ""

        for licence_type, key_prefix in self.KEY_PREFIXES.items():
            if prefix == key_prefix:
                return licence_type

        return None

    async def get_licence_by_key(self, licence_key: str) -> Optional[Licence]:
        """Get a licence by its key."""
        if not self.validate_key_format(licence_key):
            return None

        result = await self.db.execute(
            select(Licence).where(Licence.licence_key == licence_key)
        )
        return result.scalar_one_or_none()

    def is_key_expired(self, licence: Licence) -> bool:
        """Check if a licence key is expired."""
        if not licence.expires_at:
            return False
        return datetime.utcnow() > licence.expires_at

    def days_until_expiry(self, licence: Licence) -> int:
        """Calculate days until licence expiry."""
        if not licence.expires_at:
            return -1  # No expiry

        delta = licence.expires_at - datetime.utcnow()
        return max(0, delta.days)

    def calculate_renewal_expiry(
        self,
        licence: Licence,
        extend_days: Optional[int] = None,
    ) -> datetime:
        """Calculate new expiry date for renewal.

        If the licence is not expired, adds to existing expiry.
        If expired, calculates from current date.
        """
        if extend_days:
            extension = timedelta(days=extend_days)
        else:
            extension = self.get_default_validity(licence.licence_type)

        if licence.expires_at and licence.expires_at > datetime.utcnow():
            # Add to existing expiry
            return licence.expires_at + extension
        else:
            # Calculate from now
            return datetime.utcnow() + extension
