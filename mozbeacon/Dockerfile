# One image, three entrypoints: the API service, the nightly worker Job and the
# migration Job share a build, so the worker can never run against a schema the API
# doesn't know about.
#
# Build context is the repository root, not mozbeacon/, so that deploy/ is reachable.
#   docker build -f mozbeacon/Dockerfile --target runtime .

FROM ghcr.io/astral-sh/uv:0.9.28-python3.13-bookworm-slim AS deps

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Resolved from the manifest pair alone, so this layer only rebuilds when pyproject.toml
# or uv.lock change. --frozen is the load-bearing flag: it fails rather than
# re-resolving, so an image can never be built from a lock that doesn't match
# pyproject.toml. There is no second `uv sync` after the source copy because the
# project is not a package (see [tool.uv] in pyproject.toml), so nothing to install.
COPY mozbeacon/pyproject.toml mozbeacon/uv.lock mozbeacon/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev


FROM deps AS deps-dev

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project


FROM python:3.13-slim-bookworm AS runtime-base

# mozdetect pulls matplotlib and PyQt5, which link against libGL and glib.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=mozbeacon.config.settings

WORKDIR /app

COPY deploy/ /usr/local/bin/
RUN chmod +x /usr/local/bin/*.sh

# Runs before every command so that a mounted service account key is picked up whether
# the container is serving, running the nightly job, or running a one-off manage.py.
ENTRYPOINT ["docker-entrypoint.sh"]


# Deployed image: API service, worker Job and migration Job all run from this.
FROM runtime-base AS runtime

COPY --from=deps /opt/venv /opt/venv
COPY mozbeacon/ /app/

RUN useradd --create-home --uid 10001 mozbeacon && chown -R mozbeacon:mozbeacon /app
USER mozbeacon

EXPOSE 8000
CMD ["entrypoint-api.sh"]


# Local image: adds pytest and ruff, stays root so a bind-mounted source tree is
# writable. docker-compose builds this target.
FROM runtime-base AS dev

COPY --from=deps-dev /opt/venv /opt/venv
COPY mozbeacon/ /app/

EXPOSE 8000
CMD ["entrypoint-api.sh"]
