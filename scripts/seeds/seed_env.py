"""Environment setup for seeding scripts."""

import os
from pathlib import Path

def setup_seed_environment():
    """Setup environment variables for seeding."""
    # Check if .env file exists in parent directory - load it FIRST
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        print(f"[INFO] Using .env file: {env_file}")
        # Load .env file if it exists (with override to use .env values)
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file, override=True)
        except ImportError:
            print("[WARN] python-dotenv not installed, using default values")
    else:
        print("[WARN] No .env file found, using default values for seeding")

    # Set fallback defaults AFTER loading .env (only if not already set)
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/ispbilling")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
    os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
    os.environ.setdefault("SECRET_KEY", "seed-secret-key-for-development-only")
    os.environ.setdefault("MPESA_CONSUMER_KEY", "dummy-consumer-key")
    os.environ.setdefault("MPESA_CONSUMER_SECRET", "dummy-consumer-secret")
    os.environ.setdefault("MPESA_PASSKEY", "dummy-passkey")
    os.environ.setdefault("MPESA_SHORTCODE", "123456")
    os.environ.setdefault("MPESA_CALLBACK_URL", "http://localhost:8000/api/v1/mpesa/callback")

# Setup environment when this module is imported
setup_seed_environment()
