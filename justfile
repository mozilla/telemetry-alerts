# Task runner. Run from anywhere in the repository.
#
# Everything runs in the backend container, so there is one runtime and it is the one
# that gets deployed. The host virtualenv exists only so your editor can resolve imports
# and discover tests, and no recipe below uses it.
#
# The exceptions are the recipes that manage dependencies rather than run code. uv is a
# host tool and is not installed in the image, so `setup`, `lock` and `lock-check` run on
# the host. After changing dependencies, rebuild with `just build-dev`.
#
# Two rules keep this honest:
#
#   1. Every recipe is the command CI runs, not a convenience variant of it.
#      .github/workflows/ci.yml invokes these recipes rather than duplicating them, and
#      the deploy workflows should build with `just build` when they land. The moment
#      `just test` and ci.yml diverge, the local signal is worthless and people stop
#      trusting it.
#   2. `lint` and `format` are the pre-commit hooks themselves rather than a second copy
#      of the same ruff invocation, so the two cannot disagree. They run on the host,
#      since pre-commit manages its own hook environments.

# Creates a container per invocation, which costs about 1.4s over running on the host.
# That is the price of not maintaining a second environment.
mb := "docker compose run --rm backend"

# For anyone whose habit is `just format`. Drop this if you would rather have one name.
alias format := lint

# Show the available recipes.
default:
    @just --list

# Build the image, sync the host virtualenv for your editor, install the git hooks.
setup:
    docker compose build backend
    uv sync --directory mozbeacon
    pre-commit install

# Re-resolve the dependency lock after editing pyproject.toml, then rebuild.
lock:
    uv lock --directory mozbeacon
    docker compose build backend

# Fail if uv.lock and pyproject.toml disagree. CI runs this before anything else.
lock-check:
    uv lock --directory mozbeacon --check

# Rebuild the local image.
build-dev:
    docker compose build backend

# Start Postgres and the API in the background. The API autoreloads on code changes.
start:
    docker compose up -d

# Start Postgres on its own. Published on 5433, since Treeherder's container owns 5432.
db:
    docker compose up -d postgres

# Follow the API logs.
logs:
    docker compose logs -f backend

# Run the API in the foreground, so you can watch it and stop it with ctrl-c.
api:
    docker compose up backend

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

# Django shell.
shell:
    {{mb}} python manage.py shell

# Run the suite. Args pass through, so `just test -k label -x` works.
test *args:
    {{mb}} pytest {{args}}

# Fix formatting and lints in place, exiting nonzero if anything needed fixing.
lint *args:
    pre-commit run --all-files {{args}}

# Nightly detection.
detect *args:
    {{mb}} python manage.py detect {{args}}

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

# Build the deployed image. Takes a tag, so the deploy workflow pushes an image built
# by this recipe rather than by a command that only exists in CI.
build tag="mozbeacon:latest":
    docker build -f mozbeacon/Dockerfile --target runtime -t {{tag}} .

# Serve the dashboard on http://localhost:8080.
ui-dev:
    python3 -m http.server 8080 --directory ui

# No `schema` recipe yet, since the OpenAPI schema and its drift check need the api
# app from Phase 6.

# Everything CI needs to be green.
ci: lock-check lint migrate-check test
