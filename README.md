# telemetry-alerts

Telemetry change detection and alerting, split out of Treeherder. See
[migration_plan.md](migration_plan.md) for the plan this repository is being built
against, and which phase each piece belongs to.

| Path | What it is |
| :--- | :--- |
| `mozbeacon/` | The Python service. Django project, `DJANGO_SETTINGS_MODULE=mozbeacon.config.settings` |
| `mozbeacon/mozbeacon/model/` | The three tables: signature, alert summary, alert |
| `mozbeacon/mozbeacon/detection/` | The ported detection package: detector, alert manager, bug and email writers |
| `mozbeacon/mozbeacon/services/` | Pushes (Treeherder API) and Taskcluster notify |
| `mozbeacon/mozbeacon/api/` | DRF read API (Phase 6) |
| `ui/` | The alert dashboard |
| `deploy/` | Cloud Run entrypoints. One image, three of them |

## Local development

`just` is the entry point. `just --list` shows everything, and the recipes work from
anywhere in the repository:

```bash
just setup      # uv sync, plus the git hooks
just start      # Postgres and the backend, in the background
just migrate
just test       # args pass through, so `just test -k label -x` works
just api        # http://localhost:8000
just ci         # everything CI needs to be green
```

Every recipe is the command CI runs rather than a convenience variant, so the local
signal stays worth trusting. The raw commands are below for when you need them.

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
`mozbeacon/tests/`. No network or BigQuery access is needed. `tests/detection/` fakes
the `mozdetect` module through `sys.modules` and stubs the HTTP calls with `responses`.

## Configuration

Settings are read from the environment via `django-environ`, with local-development
defaults in `mozbeacon/mozbeacon/config/settings.py`. The ones that matter:

| Variable | Default | Notes |
| :--- | :--- | :--- |
| `DATABASE_URL` | `psql://mozbeacon:mozbeacon@localhost:5433/telemetry_alerts` | |
| `TELEMETRY_ENABLE_BUGS` | `False` | Outbound kill switch. Off means no bug is filed or modified |
| `TELEMETRY_ENABLE_EMAILS` | `False` | Outbound kill switch. Off means no email is sent |
| `BUG_FILER_API_KEY` | none | Creates bugs |
| `BUG_COMMENTER_API_KEY` | none | Writes `see_also` and attachments. Both keys are required |
| `NOTIFY_CLIENT_ID` / `NOTIFY_ACCESS_TOKEN` | none | Taskcluster notify |
| `ANDROID_PROBE_ALLOWLIST` | the six probes hardcoded in Treeherder today | Comma-separated |
| `BIGQUERY_PROJECT` | `mozdata` | Project the telemetry datasets are read through |
| `TREEHERDER_API_URL` | `https://treeherder.mozilla.org/api` | Pushes are read from here |

### BigQuery credentials for local detection

Detection reads telemetry from BigQuery, which needs Application Default Credentials.
Deployment and local development authenticate differently, but both arrive as
Application Default Credentials, so the detector checks once at the start of a run and
fails immediately with a message naming both mechanisms if neither produced any.

Locally, use a gcloud login:

```bash
gcloud auth application-default login
docker compose run --rm backend python manage.py test_alert --probe <probe> --max-detections 1
```

That needs a `.env` at the repository root, which docker compose reads automatically.
It is gitignored, so create your own:

```bash
# BigQuery credentials for local detection runs. Point this at your gcloud config
# directory after running `gcloud auth application-default login`. The directory is
# mounted read-only at /gcloud in the backend container, and CLOUDSDK_CONFIG points
# the BigQuery client at it.
GCLOUD_DIR=~/.config/gcloud

# A service account key on the host, to exercise the deployed credential path locally
# instead of a gcloud login. Compose mounts it where the image entrypoint expects it.
#GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json

# BigQuery project the telemetry datasets are read through. Leave as mozdata locally.
#BIGQUERY_PROJECT=mozdata

# Outbound. Both default to off. Turning either on locally sends real bugs and email.
#TELEMETRY_ENABLE_BUGS=0
#TELEMETRY_ENABLE_EMAILS=0
```

`GCLOUD_DIR` is mounted read-only at `/gcloud` and `CLOUDSDK_CONFIG` points the client
at it, so it resolves the same whichever user the container runs as. `test_alert` rolls
back its database writes unless you pass `--keep`, and files no bugs or email while the
two kill switches are off.

In deployment, mount a service account key instead. The image entrypoint exports
`GOOGLE_APPLICATION_CREDENTIALS` when it finds a key at `BQ_CREDENTIALS_PATH`
(default `/bq-credentials/credentials.json`), so on Cloud Run the whole setup is a
secret file mount:

```
--set-secrets=/bq-credentials/credentials.json=bigquery-sa-key:latest
```

An already-set `GOOGLE_APPLICATION_CREDENTIALS` always wins, so pointing it at another
path works too. To exercise this path locally rather than a gcloud login, set
`GOOGLE_APPLICATION_CREDENTIALS` in `.env` to the key's path on the host and compose
mounts it where the entrypoint expects it.

Set `BIGQUERY_PROJECT` to the project that should be billed for the queries, or to an
empty value to let the client infer it from the credentials, which is what Treeherder
does in production.

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

`just build` builds the deployed image, and `just test-docker` runs the suite inside
it.
