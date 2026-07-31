#!/bin/sh
# Migrations run as their own Cloud Run Job, never on service startup: the Phase 5
# history load writes explicit IDs and setvals the sequences, and that ordering has to
# be under our control rather than racing an autoscaled API container.
set -eu

exec python manage.py migrate --noinput "$@"
