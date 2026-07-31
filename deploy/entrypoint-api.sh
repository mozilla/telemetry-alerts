#!/bin/sh
# Cloud Run service entrypoint.
set -eu

exec gunicorn mozbeacon.config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile -
