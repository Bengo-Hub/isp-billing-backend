#!/bin/bash
set -e

# Migrations are now handled by Helm pre-install/pre-upgrade hooks
# to ensure they run before app deployment, not during app startup
# This prevents pod crash loops if migrations fail
# echo "Running Alembic migrations..."
# alembic upgrade head

echo "Starting application..."
exec "$@"

