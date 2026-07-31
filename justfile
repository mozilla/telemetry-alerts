# Task runner for both stacks. Run from anywhere in the repository.
#
# Two rules keep this honest:
#
#   1. Every recipe is the command CI runs, not a convenience variant of it. When
#      .github/workflows/ lands it should invoke these recipes rather than duplicate
#      them. The moment `just test` and ci.yml diverge, the local signal is worthless
#      and people stop trusting it.
#   2. `lint` matches .pre-commit-config.yaml. Both use ruff, and the version is pinned
#      in two places that have to agree: the dev dependency group in
#      mozbeacon/pyproject.toml and the hook rev in .pre-commit-config.yaml.
#
# The backend runs through `uv run --directory mozbeacon` so no recipe depends on where
# you invoked it from.

mb := "uv run --directory mozbeacon"

# Show the available recipes.
default:
    @just --list

# Install the backend toolchain and the git hooks.
setup:
    uv sync --directory mozbeacon
    pre-commit install

# Re-resolve the dependency lock after editing pyproject.toml.
lock:
    uv lock --directory mozbeacon

# Fail if uv.lock and pyproject.toml disagree. CI runs this before anything else.
lock-check:
    uv lock --directory mozbeacon --check

# Start Postgres and the backend in the background.
start:
    docker compose up -d

# Start Postgres. Published on 5433, since Treeherder's own container owns 5432.
db:
    docker compose up -d postgres

# Stop everything, keeping the database volume.
down:
    docker compose down

# Apply migrations.
migrate *args:
    {{mb}} python manage.py migrate {{args}}

# Generate migrations for a model change.
makemigrations *args:
    {{mb}} python manage.py makemigrations {{args}}

# Fail if a model change has no migration. CI runs this.
migrate-check:
    {{mb}} python manage.py makemigrations --check --dry-run

# Serve the API on http://localhost:8000.
api:
    {{mb}} python manage.py runserver

# Django shell.
shell:
    {{mb}} python manage.py shell

# Run the backend suite. Args pass through, so `just test -k label -x` works.
test *args:
    {{mb}} pytest {{args}}

# Run the backend suite inside the container, which is what CI builds and deploys.
test-docker *args:
    docker compose run --rm backend pytest {{args}}

# Check formatting and lints without changing anything. CI runs this.
lint:
    {{mb}} ruff check .
    {{mb}} ruff format --check .

# Apply the fixes that `lint` reports.
fmt:
    {{mb}} ruff check --fix .
    {{mb}} ruff format .

# Run the real pre-commit hooks over every tracked file.
hooks:
    pre-commit run --all-files

# Accepts --probe-filter, --platform-filter, --label-filter and --max-detections.
# Needs BigQuery credentials, see the README.

# Nightly detection.
detect *args:
    {{mb}} python manage.py detect {{args}}

# The fast-iteration path this migration exists to enable.

# Detection against one probe, rolled back afterwards unless you pass --keep.
test-alert *args:
    {{mb}} python manage.py test_alert {{args}}

# Print a test bug without filing it.
test-alert-bug *args:
    {{mb}} python manage.py test_alert_bug --dry-run {{args}}

# File a real test bug on Bugzilla.
test-alert-bug-file *args:
    {{mb}} python manage.py test_alert_bug {{args}}

# Print a test email without sending it.
test-alert-email *args:
    {{mb}} python manage.py test_alert_email --dry-run {{args}}

# Send a real test email.
test-alert-email-send *args:
    {{mb}} python manage.py test_alert_email {{args}}

# Context is the repository root so that deploy/ is reachable.

# Build the deployed image.
build:
    docker build -f mozbeacon/Dockerfile --target runtime -t mozbeacon:latest .

# Static files today, so there is no bundler and no `test-ui`. Both arrive when the
# dashboard gains a build system, at which point `test` splits into test-mozbeacon
# and test-ui.

# Serve the dashboard on http://localhost:8080.
ui-dev:
    python3 -m http.server 8080 --directory ui

# No `schema` recipe yet, since the OpenAPI schema and its drift check need the api
# app from Phase 6.

# Everything CI needs to be green.
ci: lock-check lint migrate-check test
