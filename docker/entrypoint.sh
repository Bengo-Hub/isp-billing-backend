#!/bin/bash
set -e

export PYTHONUNBUFFERED=1

# Run alembic migrations (idempotent). We keep this in the entrypoint
# so that fresh deployments auto-migrate. Use retries and do **not** exit
# the container on transient failures to avoid crash loops; manual
# intervention can be used if persistent failures occur.
MAX_RETRIES=${MIGRATION_RETRIES:-1}
for i in $(seq 1 $MAX_RETRIES); do
  echo "[MIGRATE] Running Alembic migrations (attempt $i/$MAX_RETRIES)..."
  if alembic upgrade head; then
    echo "[MIGRATE] Migrations applied"
    break
  else
    echo "[MIGRATE] Migrations failed on attempt $i"
    # Wait a bit before retrying
    if [ $i -lt $MAX_RETRIES ]; then
      sleep 5
    fi
  fi
done

# Run production seeds idempotently (non-destructive by default).
# We attempt a few retries but intentionally do not use --clear here.
SEED_RETRIES=${SEED_RETRIES:-1}
for i in $(seq 1 $SEED_RETRIES); do
  echo "[SEED] Running production seeds (attempt $i/$SEED_RETRIES)..."
  if python scripts/seeds/seed_all.py --env production; then
    echo "[SEED] Production seeds completed"
    break
  else
    echo "[SEED] Production seeds failed on attempt $i"
    if [ $i -lt $SEED_RETRIES ]; then
      sleep 5
    fi
  fi
done

# Continue to start the main process regardless of migration/seed errors.
# This avoids crash loops and lets operators inspect logs and take manual steps
# via kubectl if needed.

echo "Starting application..."
exec "$@"

