"""Centralized secrets management with encryption support.

This module provides secure handling of sensitive data including:
- Encryption/decryption of credentials
- Key derivation for secure storage
- Validation of production secrets
"""

import base64
import hashlib
import os
import secrets
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.exceptions import ConfigurationError


class SecretsManager:
    """Manage encrypted secrets with key derivation and rotation support.

    This class provides secure encryption and decryption of sensitive data
    using Fernet symmetric encryption. It supports key derivation from
    master passwords and validates that production environments have
    properly configured encryption keys.

    Attributes:
        _fernet: The Fernet cipher instance for encryption/decryption.
        _key: The encryption key being used.
    """

    def __init__(
        self,
        encryption_key: Optional[str] = None,
        master_password: Optional[str] = None,
        salt: Optional[bytes] = None,
    ):
        """Initialize the SecretsManager.

        Args:
            encryption_key: Base64-encoded Fernet key. If not provided,
                will attempt to derive from master_password.
            master_password: Password to derive encryption key from.
                Used only if encryption_key is not provided.
            salt: Salt for key derivation. Should be stored securely
                and reused for the same master_password.

        Raises:
            ConfigurationError: If no valid encryption method is provided
                or if the encryption key is invalid.
        """
        self._key: Optional[bytes] = None
        self._fernet: Optional[Fernet] = None

        if encryption_key:
            self._initialize_with_key(encryption_key)
        elif master_password:
            self._initialize_with_password(master_password, salt)
        else:
            # Try to get from environment
            env_key = os.environ.get("ENCRYPTION_KEY")
            env_password = os.environ.get("MASTER_PASSWORD")
            env_salt = os.environ.get("ENCRYPTION_SALT")

            if env_key:
                self._initialize_with_key(env_key)
            elif env_password:
                salt_bytes = (
                    base64.b64decode(env_salt) if env_salt else self._generate_salt()
                )
                self._initialize_with_password(env_password, salt_bytes)
            else:
                raise ConfigurationError(
                    "No encryption key or master password provided. "
                    "Set ENCRYPTION_KEY or MASTER_PASSWORD environment variable."
                )

    def _initialize_with_key(self, key: str) -> None:
        """Initialize Fernet with a base64-encoded key.

        Args:
            key: Base64-encoded Fernet key.

        Raises:
            ConfigurationError: If the key is invalid.
        """
        try:
            self._key = key.encode() if isinstance(key, str) else key
            self._fernet = Fernet(self._key)
        except (ValueError, InvalidToken) as e:
            raise ConfigurationError(
                f"Invalid encryption key format. Must be a valid Fernet key: {e}"
            )

    def _initialize_with_password(
        self, password: str, salt: Optional[bytes] = None
    ) -> None:
        """Derive encryption key from password using PBKDF2.

        Args:
            password: Master password to derive key from.
            salt: Salt for key derivation. Generates new one if not provided.

        Raises:
            ConfigurationError: If key derivation fails.
        """
        try:
            if salt is None:
                salt = self._generate_salt()

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=600_000,  # OWASP recommended minimum
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            self._key = key
            self._fernet = Fernet(key)
        except Exception as e:
            raise ConfigurationError(f"Failed to derive encryption key: {e}")

    @staticmethod
    def _generate_salt() -> bytes:
        """Generate a cryptographically secure random salt.

        Returns:
            16-byte random salt.
        """
        return secrets.token_bytes(16)

    @staticmethod
    def generate_key() -> str:
        """Generate a new random Fernet encryption key.

        Returns:
            Base64-encoded Fernet key suitable for use as ENCRYPTION_KEY.
        """
        return Fernet.generate_key().decode()

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string.

        Args:
            plaintext: The string to encrypt.

        Returns:
            Base64-encoded encrypted ciphertext.

        Raises:
            ConfigurationError: If encryption fails.
        """
        if self._fernet is None:
            raise ConfigurationError("SecretsManager not properly initialized")

        try:
            encrypted = self._fernet.encrypt(plaintext.encode())
            return encrypted.decode()
        except Exception as e:
            raise ConfigurationError(f"Encryption failed: {e}")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt an encrypted string.

        Args:
            ciphertext: Base64-encoded encrypted string.

        Returns:
            Decrypted plaintext string.

        Raises:
            ConfigurationError: If decryption fails (wrong key or corrupted data).
        """
        if self._fernet is None:
            raise ConfigurationError("SecretsManager not properly initialized")

        try:
            decrypted = self._fernet.decrypt(ciphertext.encode())
            return decrypted.decode()
        except InvalidToken:
            raise ConfigurationError(
                "Decryption failed: Invalid token. "
                "The encryption key may have changed or data is corrupted."
            )
        except Exception as e:
            raise ConfigurationError(f"Decryption failed: {e}")

    def encrypt_dict(self, data: dict) -> dict:
        """Encrypt sensitive values in a dictionary.

        Encrypts values for keys containing 'password', 'secret', 'key', or 'token'.

        Args:
            data: Dictionary with potentially sensitive values.

        Returns:
            Dictionary with sensitive values encrypted.
        """
        sensitive_keys = {"password", "secret", "key", "token", "credential"}
        result = {}

        for k, v in data.items():
            if isinstance(v, str) and any(s in k.lower() for s in sensitive_keys):
                result[k] = self.encrypt(v)
            elif isinstance(v, dict):
                result[k] = self.encrypt_dict(v)
            else:
                result[k] = v

        return result

    def decrypt_dict(self, data: dict) -> dict:
        """Decrypt sensitive values in a dictionary.

        Decrypts values for keys containing 'password', 'secret', 'key', or 'token'.

        Args:
            data: Dictionary with encrypted values.

        Returns:
            Dictionary with sensitive values decrypted.
        """
        sensitive_keys = {"password", "secret", "key", "token", "credential"}
        result = {}

        for k, v in data.items():
            if isinstance(v, str) and any(s in k.lower() for s in sensitive_keys):
                try:
                    result[k] = self.decrypt(v)
                except ConfigurationError:
                    # Value might not be encrypted, keep as-is
                    result[k] = v
            elif isinstance(v, dict):
                result[k] = self.decrypt_dict(v)
            else:
                result[k] = v

        return result

    @staticmethod
    def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
        """Hash a password using PBKDF2-SHA256.

        This is for general password hashing, not for encryption key derivation.
        For user password hashing, prefer passlib/bcrypt.

        Args:
            password: Password to hash.
            salt: Optional salt string. Generates new one if not provided.

        Returns:
            Tuple of (hash, salt) both as hex strings.
        """
        if salt is None:
            salt = secrets.token_hex(16)

        password_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), iterations=600_000
        )
        return password_hash.hex(), salt

    @staticmethod
    def verify_password_hash(
        password: str, password_hash: str, salt: str
    ) -> bool:
        """Verify a password against a PBKDF2-SHA256 hash.

        Args:
            password: Password to verify.
            password_hash: Expected hash as hex string.
            salt: Salt used during hashing.

        Returns:
            True if password matches, False otherwise.
        """
        computed_hash, _ = SecretsManager.hash_password(password, salt)
        return secrets.compare_digest(computed_hash, password_hash)


@lru_cache()
def get_secrets_manager() -> SecretsManager:
    """Get cached SecretsManager instance.

    Returns:
        Singleton SecretsManager instance.

    Raises:
        ConfigurationError: If encryption is not properly configured.
    """
    return SecretsManager()


def validate_production_secrets() -> list[str]:
    """Validate that production secrets are properly configured.

    Returns:
        List of warning/error messages, empty if all is well.
    """
    issues = []
    env = os.environ.get("ENVIRONMENT", "development")

    if env != "production":
        return issues

    # Check for required secrets
    required_secrets = [
        "SECRET_KEY",
        "DATABASE_URL",
        "ENCRYPTION_KEY",
    ]

    for secret in required_secrets:
        value = os.environ.get(secret)
        if not value:
            issues.append(f"Missing required secret: {secret}")
        elif len(value) < 32:
            issues.append(f"Secret {secret} appears too short for production use")

    # Check for default/example values
    dangerous_defaults = [
        ("SECRET_KEY", ["changeme", "secret", "your-secret-key"]),
        ("DATABASE_URL", ["localhost", "127.0.0.1"]),
        ("ENCRYPTION_KEY", ["default", "changeme"]),
    ]

    for secret, defaults in dangerous_defaults:
        value = os.environ.get(secret, "")
        if any(d in value.lower() for d in defaults):
            issues.append(
                f"Secret {secret} appears to contain default/example values"
            )

    return issues
