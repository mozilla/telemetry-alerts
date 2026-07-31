# telemetry-alerts

Telemetry change detection and alerting, split out of Treeherder. See
[migration_plan.md](migration_plan.md) for the plan this repository is being built
against, and which phase each piece belongs to.

| Path | What it is |
| :--- | :--- |
| `mozbeacon/` | The Python service. Django project, `DJANGO_SETTINGS_MODULE=mozbeacon.config.settings` |
| `mozbeacon/mozbeacon/model/` | The three tables — signature, alert summary, alert |
| `mozbeacon/mozbeacon/detection/` | The ported detection package. Still imports `treeherder.*`; Phase 3 rewires it |
| `mozbeacon/mozbeacon/api/` | DRF read API (Phase 6) |
| `ui/` | The alert dashboard |
| `deploy/` | Cloud Run entrypoints — one image, three of them |

## Local development

Two ways to run, both against the same Postgres. Everything below is run from the
repository root unless noted.

### Docker

```bash
docker compose up -d postgres            # Postgres 17, published on host port 5433
docker compose run --rm backend python manage.py migrate
docker compose run --rm backend pytest -q
docker compose up backend                # API on http://localhost:8000/health/
```

Port 5433, not 5432: Treeherder's own Postgres container owns 5432 on a development
machine.

The source tree is bind-mounted into the container, so edits take effect without a
rebuild. Rebuild only when `pyproject.toml` or `uv.lock` change:

```bash
docker compose build backend
```

### On the host

```bash
cd mozbeacon
uv sync                                  # creates mozbeacon/.venv
uv run pytest -q
uv run python manage.py migrate
uv run python manage.py runserver
```

`uv sync` installs the dev group as well; the deployed image doesn't. The default
`DATABASE_URL` already points at the compose Postgres on 5433, so `docker compose up -d
postgres` is still the quickest way to get a database.

## Tests

`pytest` is configured in `mozbeacon/pyproject.toml` and collects from
`mozbeacon/tests/`. `tests/detection/` is the set of files copied over from Treeherder
and is skipped by `tests/conftest.py` until Phase 3 rewires their imports.

## Configuration

Settings are read from the environment via `django-environ`, with local-development
defaults in `mozbeacon/mozbeacon/config/settings.py`. The ones that matter:

| Variable | Default | Notes |
| :--- | :--- | :--- |
| `DATABASE_URL` | `psql://mozbeacon:mozbeacon@localhost:5433/telemetry_alerts` | |
| `TELEMETRY_ENABLE_BUGS` | `False` | Outbound kill switch. Off means no bug is filed or modified |
| `TELEMETRY_ENABLE_EMAILS` | `False` | Outbound kill switch. Off means no email is sent |
| `BUG_FILER_API_KEY` | — | Creates bugs |
| `BUG_COMMENTER_API_KEY` | — | Writes `see_also` and attachments. Both keys are required |
| `NOTIFY_CLIENT_ID` / `NOTIFY_ACCESS_TOKEN` | — | Taskcluster notify |
| `ANDROID_PROBE_ALLOWLIST` | the six probes hardcoded in Treeherder today | Comma-separated |

Both kill switches default to off, so nothing in a local or shadow run can reach
Bugzilla or email without being turned on deliberately.

## Images

One image, three entrypoints, so the worker can never run against a schema the API
doesn't know about.

```bash
docker build -f mozbeacon/Dockerfile --target runtime -t mozbeacon:dev .
```

`deploy/entrypoint-api.sh` (Cloud Run service), `deploy/entrypoint-worker.sh` (nightly
Job) and `deploy/entrypoint-migrate.sh` (migration Job, never on service startup).

A `justfile` replaces the commands above once the command surface stops moving —
Phase 9, deliberately after cutover.
