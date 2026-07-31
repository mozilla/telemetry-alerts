#!/bin/sh
# Nightly detection run — Cloud Run Job entrypoint, scheduled by Cloud Scheduler.
# Cloud Scheduler owns the schedule, so there is no time window check in the code.
set -eu

exec python manage.py detect "$@"
