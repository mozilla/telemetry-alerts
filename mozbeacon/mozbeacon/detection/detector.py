"""Telemetry change detection.

The body of this module is Treeherder's Sherlock.telemetry_alert() and its helpers,
ported over unchanged apart from what the move forces: pushes come from Treeherder's
API rather than a local table, and the repository and framework are constants rather
than rows.

Sherlock's other half, perf alert backfilling, stayed in Treeherder, which is why
this is Detector rather than Sherlock.
"""

import logging
import traceback
from datetime import UTC, datetime, timedelta
from json import loads

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from mozbeacon.detection.alert import TelemetryAlertFactory
from mozbeacon.detection.alert_manager import TelemetryAlertManager
from mozbeacon.detection.probe import TelemetryProbe, TelemetryProbeValidationError
from mozbeacon.detection.utils import (
    ANDROID_ALERT_EMAIL,
    ANDROID_PROBE_ALLOWLIST,
    DEFAULT_ALERT_EMAIL,
    DESKTOP,
    MOBILE,
    is_regression,
)
from mozbeacon.model.models import (
    PerformanceTelemetryAlert,
    PerformanceTelemetryAlertSummary,
    PerformanceTelemetrySignature,
)
from mozbeacon.services.push import PushService

logger = logging.getLogger(__name__)

BUILDID_MAPPING = "https://hg.mozilla.org/mozilla-central/json-firefoxreleases"
BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"

# Were Repository and PerformanceFramework rows in Treeherder. Neither table exists
# here, and the framework is only ever "telemetry".
REPOSITORY = "mozilla-central"
FRAMEWORK = "telemetry"


class Detector:
    """Runs telemetry change detection and turns the detections into alerts."""

    def __init__(self, push_service: PushService = None):
        self.push_service = push_service or PushService()
        self._buildid_mappings = {}

    def telemetry_alert(
        self,
        probe_filter=None,
        max_detections=None,
        platform_filter=None,
        label_filter=None,
        force_monitor=False,
    ):
        """Run telemetry change detection and alert management.

        :param probe_filter: If set, only the probe with this name is processed.
            Useful for locally testing a single probe.
        :param max_detections: If set, at most this many detections per platform
            are turned into alerts. Set to 1 to exercise the alert manager with a
            single detection.
        :param platform_filter: If set to DESKTOP or MOBILE, only probes for that
            platform type are processed.
        :param label_filter: If set, only this label of a labeled probe is
            processed. Ignored for probes that aren't labeled.
        :param force_monitor: If True, probes are monitored even when their
            definition doesn't enable change detection. Used for locally testing
            probes that aren't monitored yet.
        """
        if not settings.TELEMETRY_ENABLE_ALERTS:
            logger.info("Telemetry alerting is disabled. Enable it with TELEMETRY_ENABLE_ALERTS=1")
            return

        import mozdetect
        from mozdetect.telemetry_query import get_metric_table

        self._assert_bigquery_credentials()

        # None lets the BigQuery client infer the project from the credentials.
        project = settings.BIGQUERY_PROJECT

        ts_detectors = mozdetect.get_timeseries_detectors()

        metric_definitions = self._get_metric_definitions()

        probes = {}
        alerts = []
        for metric_info in metric_definitions:
            if probe_filter and metric_info.get("name") != probe_filter:
                continue

            if platform_filter and metric_info.get("platform") != platform_filter:
                continue

            try:
                probe = TelemetryProbe(metric_info)
            except TelemetryProbeValidationError as e:
                logger.warning(f"Failed probe validation: {str(e)}")
                continue

            # Force some android probes to be monitored if they aren't already
            if probe.is_mobile and probe.name in ANDROID_PROBE_ALLOWLIST:
                probe.monitor_info = {
                    "lower_is_better": True,
                    "detect_changes": True,
                    "alert": False,
                    "notification_emails": [ANDROID_ALERT_EMAIL],
                }

            if force_monitor:
                # Monitor the probe regardless of what its definition says. Only
                # emails are produced, and they are always routed to the default
                # alert email rather than the probe owners.
                probe.monitor_info = {
                    "lower_is_better": True,
                    "detect_changes": True,
                    "alert": False,
                    "notification_emails": [DEFAULT_ALERT_EMAIL],
                }

            if not probe.should_detect_changes():
                continue
            probes.setdefault(probe.name, probe)

            logger.info(f"Running detection for {probe.name} on {probe.platform}")
            cdf_ts_detector = ts_detectors[probe.get_change_detection_technique()]

            # Probes can have slightly different defintions between mobile and desktop
            # so we need to account for that here
            platforms = ("Windows",)
            if probe.is_mobile:
                platforms = ("Android",)

            for platform in platforms:
                logger.info(f"On Platform {platform}")

                # Labeled probes hold one timeseries per label so each of them
                # needs to be analyzed separately. Unlabeled probes have a single
                # timeseries which is denoted by a `None` label.
                for label in self._get_probe_labels(
                    probe, platform, project, label_filter=label_filter
                ):
                    if label is not None:
                        logger.info(f"On label {label}")

                    # Create the probe signature now so that we can capture when it was first
                    # seen with change detection enabled. This is used to limit how far back
                    # we go for getting historical data which reduces the risk for a large
                    # influx of bugs/emails when a probe is first analyzed.
                    # XXX: Allow multiple channels, legacy probes, and different apps
                    probe_signature, _ = PerformanceTelemetrySignature.objects.update_or_create(
                        channel="Nightly",
                        platform=platform,
                        probe=probe.name,
                        label=label or "",
                        probe_type="Glean",
                        application="Fenix" if probe.is_mobile else "Firefox",
                        defaults={"lower_is_better": probe.lower_is_better},
                    )

                    try:
                        # Get data from 30 days before the signature creation date to now
                        data = get_metric_table(
                            probe.name,
                            platform,
                            android=probe.is_mobile,
                            use_fog=True,
                            project=project,
                            from_build_date=str(
                                (probe_signature.created - timedelta(days=30)).strftime("%Y-%m-%d")
                            ),
                            label=label,
                        )
                        if data.empty:
                            logger.info("No data found")
                            continue

                        timeseries = mozdetect.TelemetryTimeSeries(data)

                        ts_detector = cdf_ts_detector(timeseries)
                        detections = ts_detector.detect_changes()

                        if max_detections is not None:
                            detections = detections[:max_detections]

                        for detection in detections:
                            # Only get buildids if there might be a detection
                            if not self._buildid_mappings:
                                self._make_buildid_to_date_mapping()
                            alert = self._create_detection_alert(
                                detection, probe, platform, probe_signature
                            )
                            if alert:
                                alerts.append(alert)
                    except Exception:
                        logger.info(f"Failed: {traceback.format_exc()}")

        if alerts:
            alert_manager = TelemetryAlertManager(probes)
            alert_manager.manage_alerts(alerts)

    def _assert_bigquery_credentials(self):
        """Fail the run up front when BigQuery credentials can't be resolved.

        Worth doing explicitly, because the per-probe loop below swallows every
        exception and logs it at info. Without this, missing credentials produce a run
        that exits successfully, creates nothing, and reports no error anywhere.

        Deployment and local development authenticate differently. Deployment mounts
        a service account key and points GOOGLE_APPLICATION_CREDENTIALS at it, while
        local runs use a gcloud login. Both arrive here as Application Default
        Credentials, so one check covers both.
        """
        import google.auth
        from google.auth.exceptions import GoogleAuthError

        try:
            google.auth.default(scopes=[BIGQUERY_SCOPE])
        except GoogleAuthError as e:
            raise ImproperlyConfigured(
                "No BigQuery credentials could be resolved. In deployment, mount the "
                "service account key and point GOOGLE_APPLICATION_CREDENTIALS at it. "
                "Locally, run `gcloud auth application-default login` and set GCLOUD_DIR "
                f"so the config directory reaches the container. ({e})"
            ) from e

    def _get_probe_labels(self, probe, platform, project, label_filter=None):
        """Get the labels of a probe that need to be analyzed.

        Labeled probe types (e.g. labeled_timing_distribution) hold a separate
        timeseries for each of their labels so all of them need to be queried, and
        alerted on, individually. Probes that aren't labeled have a single
        timeseries which is denoted here with a `None` label.

        :return list: The labels to analyze, or `[None]` for unlabeled probes.
        """
        if not probe.is_labeled:
            return [None]

        if probe.is_mobile:
            # Labels can currently only be queried for desktop/FOG probes
            logger.info(f"Skipping labeled mobile probe {probe.name}")
            return []

        from mozdetect.telemetry_query import get_metric_labels

        try:
            labels = get_metric_labels(probe.name, platform, project=project)
        except Exception:
            logger.info(f"Failed to get the labels of {probe.name}: {traceback.format_exc()}")
            return []

        if label_filter:
            labels = [label for label in labels if label == label_filter]

        if not labels:
            logger.info(f"No labels found for labeled probe {probe.name}")

        return labels

    def _create_detection_alert(
        self,
        detection: object,
        probe: TelemetryProbe,
        platform: str,
        probe_signature: PerformanceTelemetrySignature,
    ):
        detection_date = str(detection.location)
        if detection_date not in self._buildid_mappings[platform]:
            # TODO: See if we should expand the range in this situation
            detection_date = self._find_closest_build_date(detection_date, platform)

        detection_build = self._buildid_mappings[platform][detection_date]
        prev_build = self._buildid_mappings[platform][detection_build["prev_build"]]
        next_build = self._buildid_mappings[platform][detection_build["next_build"]]

        # Get the pushes for these builds
        detection_push = self.push_service.get_push(REPOSITORY, detection_build["node"])
        prev_push = self.push_service.get_push(REPOSITORY, prev_build["node"])
        next_push = self.push_service.get_push(REPOSITORY, next_build["node"])

        # Check that an alert summary doesn't already exist around this point (+/- 1 day).
        # The push timestamp is denormalized onto the summary, so this stays a plain
        # filter rather than the join it used to be.
        latest_timestamp = next_push.time + timedelta(days=1)
        oldest_timestamp = next_push.time - timedelta(days=1)
        try:
            detection_summary = PerformanceTelemetryAlertSummary.objects.filter(
                repository=REPOSITORY,
                framework=FRAMEWORK,
                push_timestamp__gte=oldest_timestamp,
                push_timestamp__lte=latest_timestamp,
            ).latest("push_timestamp")
        except PerformanceTelemetryAlertSummary.DoesNotExist:
            detection_summary = None

        if not detection_summary:
            # Create an alert summary to capture all alerts
            # that occurred on the same date range
            detection_summary, _ = PerformanceTelemetryAlertSummary.objects.get_or_create(
                repository=REPOSITORY,
                framework=FRAMEWORK,
                prev_push_revision=prev_push.revision,
                push_revision=next_push.revision,
                sheriffed=False,
                defaults={
                    "prev_push_timestamp": prev_push.time,
                    "push_timestamp": next_push.time,
                    "original_push_revision": detection_push.revision,
                    "original_push_timestamp": detection_push.time,
                    "manually_created": False,
                    "created": datetime.now(UTC),
                },
            )

        try:
            detection_alert = PerformanceTelemetryAlert.objects.get(
                summary_id=detection_summary.id, series_signature_id=probe_signature.id
            )
        except PerformanceTelemetryAlert.DoesNotExist:
            detection_alert = None

        if not detection_alert:
            detection_alert, _ = PerformanceTelemetryAlert.objects.update_or_create(
                summary_id=detection_summary.id,
                series_signature=probe_signature,
                defaults={
                    "is_regression": is_regression(detection.confidence, probe.lower_is_better),
                    "amount_pct": round(
                        (100.0 * abs(detection.new_value - detection.previous_value))
                        / float(detection.previous_value),
                        2,
                    ),
                    "amount_abs": abs(detection.new_value - detection.previous_value),
                    "sustained": True,
                    "direction": detection.direction,
                    "confidence": detection.confidence,
                    "prev_value": detection.previous_value,
                    "new_value": detection.new_value,
                    "prev_median": detection.optional_detection_info["Interpolated Median"][0],
                    "new_median": detection.optional_detection_info["Interpolated Median"][1],
                    "prev_p05": detection.optional_detection_info["Interpolated p05"][0],
                    "new_p05": detection.optional_detection_info["Interpolated p05"][1],
                    "prev_p95": detection.optional_detection_info["Interpolated p95"][0],
                    "new_p95": detection.optional_detection_info["Interpolated p95"][1],
                    "additional_data": detection.optional_detection_info.get("additional_data", {}),
                },
            )

            return TelemetryAlertFactory.construct_alert(
                telemetry_alert=detection_alert,
                telemetry_alert_summary=detection_summary,
                telemetry_signature=probe_signature,
                optional_detection_info=detection.optional_detection_info,
            )

    def _get_metric_definitions(self) -> list[dict]:
        metric_definition_urls = [
            ("https://dictionary.telemetry.mozilla.org/data/firefox_desktop/index.json", DESKTOP),
            ("https://dictionary.telemetry.mozilla.org/data/fenix/index.json", MOBILE),
        ]

        merged_metrics = []

        for url, platform in metric_definition_urls:
            try:
                logger.info(f"Getting probes from {url}")
                response = requests.get(url)
                response.raise_for_status()

                data = response.json()
                metrics = data.get("metrics", [])
                for metric in metrics:
                    merged_metrics.append(
                        {
                            "name": metric["name"].replace(".", "_"),
                            "data": metric,
                            "platform": platform,
                        }
                    )

                logger.info(f"Found {len(metrics)} probes")
            except requests.RequestException as e:
                logger.info(f"Failed to fetch from {url}: {e}")
            except ValueError:
                logger.info(f"Invalid JSON from {url}")

        return merged_metrics

    def _make_buildid_to_date_mapping(self):
        # Always returned in order of newest to oldest, only capture
        # the newest build for each day, and ignore others. This can
        # differ between platforms too (e.g. failed builds)
        buildid_mappings = self._get_buildid_mappings()

        prev_date = {}
        for build in buildid_mappings["builds"]:
            platform = self._replace_platform_build_name(build["platform"])
            if not platform:
                continue
            curr_date = str(datetime.strptime(build["buildid"][:8], "%Y%m%d").date())

            platform_builds = self._buildid_mappings.setdefault(platform, {})
            if curr_date not in platform_builds:
                platform_builds[curr_date] = build

                if prev_date.get(platform):
                    platform_builds[prev_date[platform]]["prev_build"] = curr_date
                    platform_builds[curr_date]["next_build"] = prev_date[platform]
                else:
                    platform_builds[curr_date]["next_build"] = curr_date

            prev_date[platform] = curr_date

        # Android (Fenix/GeckoView) nightlies are built from mozilla-central, so
        # the daily changeset matches the desktop builds. hg.mozilla.org doesn't
        # expose Android builds in json-firefoxreleases, so reuse the desktop
        # daily mapping rather than fetching a separate Android build source.
        for desktop_platform in ("Windows", "Linux", "Darwin"):
            if desktop_platform in self._buildid_mappings:
                self._buildid_mappings.setdefault(
                    "Android", self._buildid_mappings[desktop_platform]
                )
                break

    def _get_buildid_mappings(self) -> dict:
        try:
            response = requests.get(BUILDID_MAPPING)
            response.raise_for_status()
            return loads(response.content)
        except requests.RequestException as e:
            raise Exception(f"Failed to download buildid mappings, cannot produce detections: {e}")

    def _replace_platform_build_name(self, platform: str) -> str:
        if platform == "win64":
            return "Windows"
        if platform == "linux64":
            return "Linux"
        if platform == "mac":
            return "Darwin"
        return ""

    def _find_closest_build_date(self, detection_date: str, platform: str) -> str:
        # Get the closest date to the detection date
        prev_date = None

        for date in sorted(list(self._buildid_mappings[platform].keys())):
            if date > detection_date:
                break
            prev_date = date

        return prev_date
