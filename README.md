# telemetry-alerts

This repository contains the Mozilla telemetry alerting system. The detection system is
found in [MozDetect](https://github.com/mozilla/mozdetect).

| Path | What it is |
| :--- | :--- |
| `mozbeacon/` | The Python service (backend) |
| `mozbeacon/mozbeacon/model/` | The three tables: signature, alert summary, alert |
| `mozbeacon/mozbeacon/detection/` | The alerting system |
| `mozbeacon/mozbeacon/services/` | Pushes (Treeherder API) and Taskcluster notify |
| `mozbeacon/mozbeacon/api/` | For future API code |
| `ui/` | The alert dashboard |
| `deploy/` | Run entrypoints |

## Local development

### Prerequisites

You will need to have `docker compose` installed along with `uv` and `just`.

For `just`, you can [find instructions here](https://github.com/casey/just#installation).
Note that it's possible to run everything without `just`, it simply gives a cleaner
interface for running the commands.

### Usage

`just` is the entry point. `just --list` shows everything:

```bash
just setup      # uv sync, plus the git hooks
just start      # Postgres and the backend, in the background
just migrate
just test       # args pass through, so `just test -k label -x` works
just api        # http://localhost:8000
just ci         # everything CI needs to be green
```

## Configuration

Settings are read from the environment via `django-environ`, with local-development
defaults in `mozbeacon/mozbeacon/config/settings.py`.

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
