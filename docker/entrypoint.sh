#!/usr/bin/env bash
# Container entrypoint: ensure data dirs exist, apply migrations, then run the
# given command (gunicorn).
set -e

mkdir -p /app/data /app/usermedia

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "[entrypoint] Applying database migrations..."
    python manage.py migrate --no-input
fi

exec "$@"
