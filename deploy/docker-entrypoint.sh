#!/bin/sh
# Image entrypoint. Runs before every command. API, worker, migrations and one-off
# `manage.py` runs alike, then hands off to whatever was asked for.
set -eu

# BigQuery credentials. Deployment mounts a service account key (a Secret Manager file
# mount, or a docker volume) at BQ_CREDENTIALS_PATH, and the BigQuery client picks it up
# through GOOGLE_APPLICATION_CREDENTIALS. Local development instead mounts a gcloud
# config directory and resolves the same credentials through CLOUDSDK_CONFIG, so this
# is conditional: an already-set variable wins, and an absent key file is not an error
# here. The detector fails the run up front if neither mechanism produced credentials.
BQ_CREDENTIALS_PATH="${BQ_CREDENTIALS_PATH:-/bq-credentials/credentials.json}"
if [ -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" ] && [ -f "$BQ_CREDENTIALS_PATH" ]; then
    GOOGLE_APPLICATION_CREDENTIALS="$BQ_CREDENTIALS_PATH"
    export GOOGLE_APPLICATION_CREDENTIALS
    echo "Using BigQuery credentials at $GOOGLE_APPLICATION_CREDENTIALS"
fi

exec "$@"
