"""Fernet credential encryption helpers for stored gateway credentials.

Used to encrypt/decrypt the credentials blob on SMS / WhatsApp delivery gateway
config rows (SMSGatewayConfig / WhatsAppGatewayConfig). Extracted from the now
removed payment-gateways integration so the surviving delivery-gateway config
endpoints keep working. Falls back to plain JSON in development when no
encryption key is configured (mirrors the previous behaviour).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet

from app.core.config import settings


def encrypt_credentials(credentials: Dict[str, Any], key: Optional[str] = None) -> str:
    """Encrypt a credentials dict for storage. Plain JSON when no key set (dev)."""
    encryption_key = key or getattr(settings, "encryption_key", None)
    if not encryption_key:
        return json.dumps(credentials)
    fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
    return fernet.encrypt(json.dumps(credentials).encode()).decode()


def decrypt_credentials(encrypted: str, key: Optional[str] = None) -> Dict[str, Any]:
    """Decrypt a stored credentials blob. Falls back to plain JSON in dev."""
    encryption_key = key or getattr(settings, "encryption_key", None)
    if not encryption_key:
        return json.loads(encrypted) if encrypted else {}
    fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
    decrypted = fernet.decrypt(encrypted.encode() if isinstance(encrypted, str) else encrypted)
    return json.loads(decrypted.decode())
