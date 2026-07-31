import sys
from types import ModuleType
from unittest.mock import Mock, patch

import pytest
from django.core.exceptions import ImproperlyConfigured

from mozbeacon.detection.detector import Detector
from mozbeacon.detection.probe import TelemetryProbe
from mozbeacon.detection.utils import (
    DEFAULT_ALERT_EMAIL,
)
from mozbeacon.model.models import PerformanceTelemetrySignature


@pytest.fixture
def detector(db):
    return Detector()


@pytest.fixture
def fake_mozdetect(monkeypatch):
    """Fake mozdetect module for the lazy imports done in the Detector.

    Injected through sys.modules so that the `import mozdetect` calls made inside
    the telemetry alerting methods pick this up instead of the real module (which
    would require BigQuery access).
    """
    telemetry_query = ModuleType("mozdetect.telemetry_query")
    telemetry_query.get_metric_labels = Mock(return_value=[])
    telemetry_query.get_metric_table = Mock(return_value=Mock(empty=True))

    mozdetect = ModuleType("mozdetect")
    mozdetect.telemetry_query = telemetry_query
    mozdetect.get_timeseries_detectors = Mock(return_value={"cdf_squared": Mock()})
    mozdetect.TelemetryTimeSeries = Mock()

    monkeypatch.setitem(sys.modules, "mozdetect", mozdetect)
    monkeypatch.setitem(sys.modules, "mozdetect.telemetry_query", telemetry_query)

    return mozdetect


class TestGetProbeLabels:
    def test_unlabeled_probe_has_a_single_none_label(self, detector, base_metric_info):
        """Test unlabeled probes are analyzed once, without a label."""
        base_metric_info["data"]["monitor"] = True
        probe = TelemetryProbe(base_metric_info)

        assert detector._get_probe_labels(probe, "Windows", "mozdata") == [None]

    def test_labeled_probe_returns_queried_labels(
        self, detector, labeled_metric_info, fake_mozdetect
    ):
        """Test all the labels of a labeled probe are returned."""
        fake_mozdetect.telemetry_query.get_metric_labels.return_value = ["http", "https"]
        probe = TelemetryProbe(labeled_metric_info)

        labels = detector._get_probe_labels(probe, "Windows", "mozdata")

        assert labels == ["http", "https"]
        fake_mozdetect.telemetry_query.get_metric_labels.assert_called_once_with(
            probe.name, "Windows", project="mozdata"
        )

    def test_labeled_probe_with_label_filter(self, detector, labeled_metric_info, fake_mozdetect):
        """Test only the requested label is returned when a filter is given."""
        fake_mozdetect.telemetry_query.get_metric_labels.return_value = ["http", "https"]
        probe = TelemetryProbe(labeled_metric_info)

        labels = detector._get_probe_labels(probe, "Windows", "mozdata", label_filter="https")

        assert labels == ["https"]

    def test_labeled_probe_with_unknown_label_filter(
        self, detector, labeled_metric_info, fake_mozdetect
    ):
        """Test nothing is analyzed when the requested label doesn't exist."""
        fake_mozdetect.telemetry_query.get_metric_labels.return_value = ["http", "https"]
        probe = TelemetryProbe(labeled_metric_info)

        assert detector._get_probe_labels(probe, "Windows", "mozdata", label_filter="ftp") == []

    def test_labeled_probe_without_labels(
        self, detector, labeled_metric_info, fake_mozdetect, caplog
    ):
        """Test a labeled probe with no labels found is skipped."""
        probe = TelemetryProbe(labeled_metric_info)

        assert detector._get_probe_labels(probe, "Windows", "mozdata") == []
        assert f"No labels found for labeled probe {probe.name}" in caplog.text

    def test_labeled_probe_with_failing_label_query(
        self, detector, labeled_metric_info, fake_mozdetect, caplog
    ):
        """Test a failure while querying the labels doesn't break the run."""
        fake_mozdetect.telemetry_query.get_metric_labels.side_effect = Exception("BigQuery failed")
        probe = TelemetryProbe(labeled_metric_info)

        assert detector._get_probe_labels(probe, "Windows", "mozdata") == []
        assert f"Failed to get the labels of {probe.name}" in caplog.text

    def test_labeled_mobile_probe_is_skipped(
        self, detector, labeled_metric_info, fake_mozdetect, caplog
    ):
        """Test labeled mobile probes are skipped since their labels can't be queried."""
        labeled_metric_info["platform"] = "mobile"
        probe = TelemetryProbe(labeled_metric_info)

        assert detector._get_probe_labels(probe, "Android", "mozdata") == []
        assert f"Skipping labeled mobile probe {probe.name}" in caplog.text
        fake_mozdetect.telemetry_query.get_metric_labels.assert_not_called()


class TestTelemetryAlertWithLabeledProbes:
    def test_each_label_is_analyzed_separately(
        self,
        detector,
        labeled_metric_info,
        fake_mozdetect,
        settings,
    ):
        """Test labeled probes get their own signature, and query, per label."""
        settings.TELEMETRY_ENABLE_ALERTS = True
        fake_mozdetect.telemetry_query.get_metric_labels.return_value = ["http", "https"]

        with patch.object(Detector, "_get_metric_definitions", return_value=[labeled_metric_info]):
            detector.telemetry_alert()

        signatures = PerformanceTelemetrySignature.objects.filter(
            probe=labeled_metric_info["name"]
        ).order_by("label")
        assert [signature.label for signature in signatures] == ["http", "https"]

        queried_labels = [
            call.kwargs["label"]
            for call in fake_mozdetect.telemetry_query.get_metric_table.call_args_list
        ]
        assert queried_labels == ["http", "https"]

    def test_unlabeled_probe_is_queried_without_a_label(
        self,
        detector,
        base_metric_info,
        fake_mozdetect,
        settings,
    ):
        """Test unlabeled probes produce a single signature with no label."""
        settings.TELEMETRY_ENABLE_ALERTS = True
        base_metric_info["data"]["monitor"] = {"alert": False, "lower_is_better": True}

        with patch.object(Detector, "_get_metric_definitions", return_value=[base_metric_info]):
            detector.telemetry_alert()

        signature = PerformanceTelemetrySignature.objects.get(probe=base_metric_info["name"])
        assert signature.label == ""

        fake_mozdetect.telemetry_query.get_metric_labels.assert_not_called()
        assert fake_mozdetect.telemetry_query.get_metric_table.call_args.kwargs["label"] is None


class TestTelemetryAlertForceMonitor:
    def test_unmonitored_probe_is_skipped(
        self,
        detector,
        labeled_metric_info,
        fake_mozdetect,
        settings,
    ):
        """Test probes without change detection enabled aren't analyzed."""
        settings.TELEMETRY_ENABLE_ALERTS = True
        labeled_metric_info["data"]["monitor"] = {}
        fake_mozdetect.telemetry_query.get_metric_labels.return_value = ["http", "https"]

        with patch.object(Detector, "_get_metric_definitions", return_value=[labeled_metric_info]):
            detector.telemetry_alert()

        assert not PerformanceTelemetrySignature.objects.exists()
        fake_mozdetect.telemetry_query.get_metric_table.assert_not_called()

    def test_unmonitored_probe_is_analyzed_when_forced(
        self,
        detector,
        labeled_metric_info,
        fake_mozdetect,
        settings,
    ):
        """Test force_monitor analyzes probes that don't enable change detection."""
        settings.TELEMETRY_ENABLE_ALERTS = True
        labeled_metric_info["data"]["monitor"] = {}
        fake_mozdetect.telemetry_query.get_metric_labels.return_value = ["http", "https"]

        with patch.object(Detector, "_get_metric_definitions", return_value=[labeled_metric_info]):
            detector.telemetry_alert(force_monitor=True)

        signatures = PerformanceTelemetrySignature.objects.filter(
            probe=labeled_metric_info["name"]
        ).order_by("label")
        assert [signature.label for signature in signatures] == ["http", "https"]
        assert all(signature.lower_is_better for signature in signatures)
        assert fake_mozdetect.telemetry_query.get_metric_table.call_count == 2

    def test_forced_probe_emails_the_default_address(
        self,
        detector,
        labeled_metric_info,
        fake_mozdetect,
        settings,
    ):
        """Test forced probes only produce emails, and never to the probe owners."""
        settings.TELEMETRY_ENABLE_ALERTS = True
        labeled_metric_info["data"]["monitor"] = {}
        analyzed_probes = []

        def capture_probe(probe, *args, **kwargs):
            analyzed_probes.append(probe)
            return []

        with (
            patch.object(Detector, "_get_metric_definitions", return_value=[labeled_metric_info]),
            patch.object(Detector, "_get_probe_labels", side_effect=capture_probe),
        ):
            detector.telemetry_alert(force_monitor=True)

        probe = analyzed_probes[0]
        assert probe.should_detect_changes() is True
        assert probe.should_file_bug() is False
        assert probe.get_notification_emails() == [DEFAULT_ALERT_EMAIL]


class TestBigQueryCredentials:
    """Deployment mounts a service account key and local development uses a gcloud
    login. Both surface as Application Default Credentials, so the detector checks
    once, up front. The per-probe loop swallows exceptions and logs at info, so a
    credentials problem would otherwise be a silent no-op run."""

    def test_resolvable_credentials_pass(self, detector):
        with patch("google.auth.default", return_value=(Mock(), "mozdata")) as resolve:
            detector._assert_bigquery_credentials()

        assert resolve.call_args.kwargs["scopes"] == ["https://www.googleapis.com/auth/bigquery"]

    def test_missing_credentials_fail_the_run_up_front(self, detector):
        from google.auth.exceptions import DefaultCredentialsError

        with (
            patch("google.auth.default", side_effect=DefaultCredentialsError("not found")),
            pytest.raises(ImproperlyConfigured) as raised,
        ):
            detector._assert_bigquery_credentials()

        # The message has to name both mechanisms. Whoever hits this is in one of them.
        assert "GOOGLE_APPLICATION_CREDENTIALS" in str(raised.value)
        assert "GCLOUD_DIR" in str(raised.value)

    def test_detection_stops_before_querying_anything(self, detector, fake_mozdetect, settings):
        from google.auth.exceptions import DefaultCredentialsError

        settings.TELEMETRY_ENABLE_ALERTS = True

        with (
            patch("google.auth.default", side_effect=DefaultCredentialsError("not found")),
            pytest.raises(ImproperlyConfigured),
        ):
            detector.telemetry_alert()

        fake_mozdetect.telemetry_query.get_metric_table.assert_not_called()
