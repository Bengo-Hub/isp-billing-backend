"""
Encryption utilities for sensitive data storage.
Uses Fernet symmetric encryption for API credentials.
"""
import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend


class CredentialEncryption:
    """Handles encryption/decryption of router API credentials."""
    
    def __init__(self):
        """Initialize encryption with key from environment."""
        # Get encryption key from environment or generate one (for dev)
        encryption_key = os.getenv('ENCRYPTION_KEY','development-only-key-please-change')
        
        if not encryption_key:
            # Development only - generate from SECRET_KEY
            secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
            salt = b'router-credentials-salt'  # Static salt for consistency
            
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=default_backend()
            )
            key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
            self.fernet = Fernet(key)
        else:
            self.fernet = Fernet(encryption_key.encode())
    
    def encrypt_credentials(self, username: str, password: str) -> str:
        """Encrypt router credentials for storage.
        
        Args:
            username: Router API username
            password: Router API password
            
        Returns:
            Base64 encoded encrypted string
        """
        credentials = f"{username}:{password}"
        encrypted = self.fernet.encrypt(credentials.encode())
        return encrypted.decode()
    
    def decrypt_credentials(self, encrypted_data: str) -> dict[str, str]:
        """Decrypt router credentials.
        
        Args:
            encrypted_data: Encrypted credentials string
            
        Returns:
            Dictionary with 'username' and 'password' keys
        """
        try:
            decrypted = self.fernet.decrypt(encrypted_data.encode())
            credentials = decrypted.decode()
            username, password = credentials.split(':', 1)
            return {"username": username, "password": password}
        except Exception as e:
            raise ValueError(f"Failed to decrypt credentials: {str(e)}")


# Singleton instance
_encryption_instance = None

def get_credential_encryption() -> CredentialEncryption:
    """Get or create the credential encryption instance."""
    global _encryption_instance
    if _encryption_instance is None:
        _encryption_instance = CredentialEncryption()
    return _encryption_instance
