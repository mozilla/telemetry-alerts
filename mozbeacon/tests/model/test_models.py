"""Smoke tests for the Phase 2a schema.

These exist to prove the schema round-trips against a real Postgres and that the
uniqueness constraints the worker relies on for idempotency are actually enforced.
"""

from datetime import UTC, datetime

import pytest
from django.db import IntegrityError, transaction

from mozbeacon.model.models import (
    PerformanceTelemetryAlert,
    PerformanceTelemetryAlertSummary,
    PerformanceTelemetrySignature,
)

pytestmark = pytest.mark.django_db


def make_signature(**overrides):
    fields = {
        "channel": PerformanceTelemetrySignature.NIGHTLY,
        "platform": "windows",
        "probe": "networking_dns_lookup_time",
        "probe_type": PerformanceTelemetrySignature.GLEAN,
        "application": "firefox_desktop",
        "lower_is_better": True,
    }
    fields.update(overrides)
    return PerformanceTelemetrySignature.objects.create(**fields)


def make_summary(**overrides):
    fields = {
        "repository": "mozilla-central",
        "framework": "telemetry",
        "prev_push_revision": "a" * 40,
        "prev_push_timestamp": datetime(2026, 7, 1, tzinfo=UTC),
        "push_revision": "b" * 40,
        "push_timestamp": datetime(2026, 7, 3, tzinfo=UTC),
        "original_push_revision": "c" * 40,
        "original_push_timestamp": datetime(2026, 7, 2, tzinfo=UTC),
        "sheriffed": False,
    }
    fields.update(overrides)
    return PerformanceTelemetryAlertSummary.objects.create(**fields)


def make_alert(summary, signature, **overrides):
    fields = {
        "summary": summary,
        "series_signature": signature,
        "is_regression": True,
        "amount_pct": 12.5,
        "amount_abs": 4.0,
        "prev_value": 100.0,
        "new_value": 104.0,
        "confidence": 0.92,
        "direction": "increase",
        "prev_median": 10.0,
        "new_median": 14.0,
    }
    fields.update(overrides)
    return PerformanceTelemetryAlert.objects.create(**fields)


def test_signature_pretty_name_uses_the_label():
    assert make_signature().pretty_name == "networking_dns_lookup_time"
    labelled = make_signature(label="cached")
    assert labelled.pretty_name == "networking_dns_lookup_time (cached)"


def test_label_is_part_of_signature_uniqueness():
    """Each label of a labeled probe holds its own timeseries, so it needs its own row."""
    make_signature(label="cached")
    make_signature(label="uncached")

    with pytest.raises(IntegrityError), transaction.atomic():
        make_signature(label="cached")


def test_summary_is_unique_per_push_range():
    make_summary()

    with pytest.raises(IntegrityError), transaction.atomic():
        make_summary()

    # A different push range is a different summary.
    assert make_summary(push_revision="d" * 40).pk


def test_alert_is_unique_per_summary_and_signature():
    summary = make_summary()
    signature = make_signature()
    make_alert(summary, signature)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_alert(summary, signature)

    # A second probe alerting over the same push range joins the same summary.
    assert make_alert(summary, make_signature(probe="network_tcp_connection")).pk
    assert summary.alerts.count() == 2


def test_alert_defaults_match_the_retry_flags_the_worker_relies_on():
    alert = make_alert(make_summary(), make_signature())

    assert alert.status == PerformanceTelemetryAlert.NEW
    assert alert.bug_number is None
    assert alert.notified is False
    # bug_modified/bugs_modified default True: only a failed modification flips them
    # false, which is what house_keeping() retries on.
    assert alert.bug_modified is True
    assert alert.summary.bugs_modified is True
    assert alert.additional_data == {}


def test_created_is_stamped_on_insert():
    """auto_now_add discards any value passed in, which is why the Phase 5 history load
    has to write created out of band."""
    passed_in = datetime(2020, 1, 1, tzinfo=UTC)
    summary = make_summary(created=passed_in)

    summary.refresh_from_db()
    assert summary.created != passed_in
