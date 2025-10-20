# MPESA Integration Keys

This directory contains the cryptographic keys required for MPESA integration.

## Required Files

### Production Environment
- `mpesa_public_key.pem` - MPESA production public key for signature verification
- `mpesa_sandbox_public_key.pem` - MPESA sandbox public key for signature verification

### Key Management
1. Download the official MPESA public keys from the Safaricom Developer Portal
2. Place the appropriate key file in this directory
3. Ensure proper file permissions (read-only for the application user)
4. Never commit these keys to version control

## Key Sources
- **Production**: https://developer.safaricom.co.ke/Documentation
- **Sandbox**: https://developer.safaricom.co.ke/Documentation

## Security Notes
- Keys are loaded at runtime and cached in memory
- Keys are not logged or exposed in error messages
- File access is restricted to the application process
- Keys are validated on load to ensure they are valid PEM format

## File Naming Convention
- Production: `mpesa_public_key.pem`
- Sandbox: `mpesa_sandbox_public_key.pem`
