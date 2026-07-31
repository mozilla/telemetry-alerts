"""
Django settings for mozbeacon.

Every setting the ported detection code reads is declared here, using the same names
it already uses in Treeherder so that Phase 3 stays a straight port. Values that were
hardcoded in Treeherder — and that the migration exists to make changeable without a
deploy — are read from the environment instead.
"""

from pathlib import Path
from urllib.parse import urlparse

import environ

env = environ.Env()

# mozbeacon/mozbeacon/config/settings.py -> mozbeacon/
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

DEBUG = env.bool("DEBUG", default=False)
SECRET_KEY = env("SECRET_KEY", default="insecure-local-development-key-do-not-deploy")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

SITE_URL = env("SITE_URL", default="http://localhost:8000")
SITE_HOSTNAME = urlparse(SITE_URL).hostname

INSTALLED_APPS = [
    "rest_framework",
    "mozbeacon.model",
    "mozbeacon.detection",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "mozbeacon.config.urls"
WSGI_APPLICATION = "mozbeacon.config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

# The local default is port 5433, not 5432: Treeherder's own postgres container owns
# 5432 on a development machine and the clash is a known gotcha there.
DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default="psql://mozbeacon:mozbeacon@localhost:5433/telemetry_alerts",
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TIME_ZONE = "UTC"
USE_TZ = True
USE_I18N = False

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"standard": {"format": "%(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}

# Bugzilla. Both keys are required: the filer key creates bugs, the commenter key
# writes see_also and attachments. Provisioning only the first gives a service that
# files bugs correctly while every modification fails and retries forever.
BZ_API_URL = "https://bugzilla.mozilla.org"
BUGFILER_API_URL = env("BUGZILLA_API_URL", default=BZ_API_URL)
BUGFILER_API_KEY = env("BUG_FILER_API_KEY", default=None)
COMMENTER_API_KEY = env("BUG_COMMENTER_API_KEY", default=None)
BZ_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Taskcluster credentials for the notification service
NOTIFY_CLIENT_ID = env("NOTIFY_CLIENT_ID", default=None)
NOTIFY_ACCESS_TOKEN = env("NOTIFY_ACCESS_TOKEN", default=None)
PERF_SHERIFF_BOT_CLIENT_ID = env("PERF_SHERIFF_BOT_CLIENT_ID", default=None)
PERF_SHERIFF_BOT_ACCESS_TOKEN = env("PERF_SHERIFF_BOT_ACCESS_TOKEN", default=None)

# Detection
TELEMETRY_ENABLE_ALERTS = env.bool("TELEMETRY_ENABLE_ALERTS", default=True)
SUPPORTED_PLATFORMS = env.list("SUPPORTED_PLATFORMS", default=["windows", "linux", "osx"])

# Outbound kill switches, independent of detection, so the service can run in shadow
# mode without duplicating every bug and email that Treeherder is still sending.
# These gate the decision to file/notify, not the transport — see Phase 3.
TELEMETRY_ENABLE_BUGS = env.bool("TELEMETRY_ENABLE_BUGS", default=False)
TELEMETRY_ENABLE_EMAILS = env.bool("TELEMETRY_ENABLE_EMAILS", default=False)

# Taskcluster's notify service rate limit.
EMAIL_LIMIT = env.int("EMAIL_LIMIT", default=50)

# Hardcoded in Treeherder's telemetry_alerting/utils.py today; the defaults below are
# its current values. Moved here so that rollout changes — the Android allowlist in
# particular — don't need a deploy. Note ANDROID_ALERT_EMAIL is not just a fallback:
# it overrides the probe's own notification list for every allowlisted probe.
DEFAULT_ALERT_EMAIL = env("DEFAULT_ALERT_EMAIL", default="gmierzwinski@mozilla.com")
ANDROID_ALERT_EMAIL = env("ANDROID_ALERT_EMAIL", default="perf-telemetry-alerts@mozilla.com")
ANDROID_PROBE_ALLOWLIST = env.list(
    "ANDROID_PROBE_ALLOWLIST",
    default=[
        "perf_largest_contentful_paint",
        "performance_pageload_fcp",
        "networking_http_channel_page_open_to_first_sent",
        "networking_dns_lookup_time",
        "network_tcp_connection",
        "dns_native_lookup_time",
    ],
)
