"""
Encryption utilities for sensitive data storage.

This module provides a specialized wrapper around SecretsManager
for router API credential encryption/decryption.

Note: This uses the centralized SecretsManager from secrets.py
to avoid duplicate encryption logic and ensure consistent security.
"""
from functools import lru_cache

from app.core.secrets import get_secrets_manager
from app.core.exceptions import ConfigurationError


class CredentialEncryption:
    """Handles encryption/decryption of router API credentials.

    This is a thin wrapper around SecretsManager that provides
    a credential-specific API (username:password format).
    """

    def __init__(self):
        """Initialize encryption using the centralized SecretsManager."""
        self._secrets = get_secrets_manager()

    def encrypt_credentials(self, username: str, password: str) -> str:
        """Encrypt router credentials for storage.

        Args:
            username: Router API username
            password: Router API password

        Returns:
            Base64 encoded encrypted string
        """
        credentials = f"{username}:{password}"
        return self._secrets.encrypt(credentials)

    def decrypt_credentials(self, encrypted_data: str) -> dict[str, str]:
        """Decrypt router credentials.

        Args:
            encrypted_data: Encrypted credentials string

        Returns:
            Dictionary with 'username' and 'password' keys

        Raises:
            ValueError: If decryption fails or format is invalid
        """
        try:
            decrypted = self._secrets.decrypt(encrypted_data)
            username, password = decrypted.split(':', 1)
            return {"username": username, "password": password}
        except ConfigurationError as e:
            raise ValueError(f"Failed to decrypt credentials: {str(e)}")
        except ValueError:
            raise ValueError("Invalid credential format: expected 'username:password'")


@lru_cache()
def get_credential_encryption() -> CredentialEncryption:
    """Get cached credential encryption instance.

    Returns:
        Singleton CredentialEncryption instance.
    """
    return CredentialEncryption()


def encrypt_value(value: str) -> str:
    """Encrypt a single value for storage.

    Uses the centralized SecretsManager for encryption.
    """
    secrets = get_secrets_manager()
    return secrets.encrypt(value)


def decrypt_value(encrypted_value: str) -> str:
    """Decrypt a single encrypted value.

    Uses the centralized SecretsManager for decryption.
    """
    try:
        secrets = get_secrets_manager()
        return secrets.decrypt(encrypted_value)
    except Exception as e:
        raise ValueError(f"Failed to decrypt value: {str(e)}")
