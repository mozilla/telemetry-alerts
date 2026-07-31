"""
Telemetry alerting schema — Phase 2a.

Ported from Treeherder's treeherder/perf/models.py. The three models below were
PerformanceTelemetrySignature, PerformanceTelemetryAlertSummary and
PerformanceTelemetryAlert; the latter two inherited from PerformanceAlertSummaryBase
and PerformanceAlertBase, which are flattened here since there is nothing else in
this service to share them with.

Phase 2a deliberately keeps every column that exists today, along with its name and
its stored values, so that the Phase 5 transform is close to a straight copy and any
Phase 7 detection divergence is attributable to the port rather than to the schema.
The only changes are the ones the loss of Treeherder's tables forces:

  * repository, framework and issue_tracker collapse from ForeignKey to plain values
  * assignee/classifier collapse from ForeignKey(User) to email columns
  * the four Push foreign keys denormalize into revision/timestamp column pairs

Fields marked "2b" are the audited drops, renames and enum collapses that happen
after cutover, once there is no second implementation to stay compatible with.
"""

from django.db import models


class PerformanceTelemetrySignature(models.Model):
    id = models.BigAutoField(primary_key=True)

    NIGHTLY = "Nightly"
    BETA = "Beta"
    RELEASE = "Release"

    CHANNELS = (
        (NIGHTLY, "Mozilla-central Builds"),
        (BETA, "Mozilla-beta Builds"),
        (RELEASE, "Mozilla-release Builds"),
    )
    channel = models.CharField(max_length=30, choices=CHANNELS)
    platform = models.CharField(max_length=80)
    probe = models.CharField(max_length=80)
    label = models.CharField(
        max_length=255,
        default="",
        blank=True,
        help_text="Label of the probe for labeled probe types (e.g. "
        "labeled_timing_distribution). Each label of those probes holds its own "
        "timeseries so it needs its own signature. Empty for unlabeled probes.",
    )

    GLEAN = "Glean"
    LEGACY = "Legacy"

    PROBE_TYPES = (
        (GLEAN, "Probes that are from the Glean Telemetry System"),
        (LEGACY, "Probes that are from the Legacy Telemetry System"),
    )
    probe_type = models.CharField(max_length=30, choices=PROBE_TYPES)
    application = models.CharField(
        max_length=80,
        default="",
        help_text="Application that runs the signature's tests. "
        "Generally used to record browser's name, but not necessarily.",
    )
    # Null when the probe's direction can't be determined (e.g. lower_is_better is unset)
    lower_is_better = models.BooleanField(null=True)
    # Load-bearing, not metadata: the detector derives the BigQuery from_build_date as
    # created - 30 days, which is what stops a bug/email flood the first time a probe is
    # monitored. auto_now_add means the Phase 5 load has to write this out of band.
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "performance_telemetry_signature"
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "probe", "probe_type", "platform", "application", "label"],
                name="unique_telemetry_signature",
            )
        ]

    @property
    def pretty_name(self):
        if self.label:
            return f"{self.probe} ({self.label})"
        return self.probe

    def __str__(self):
        return (
            f"{self.pretty_name} {self.probe_type} {self.channel} "
            f"{self.platform} {self.application}"
        )


class PerformanceTelemetryAlertSummary(models.Model):
    """
    A summarization of telemetry alerts.

    Groups every alert detected over the same push range together, so that the probes
    which changed at the same time are triaged and filed as a unit.
    """

    id = models.AutoField(primary_key=True)

    # Was ForeignKey(Repository). Only ever mozilla-central today, but pushes are
    # per-repository and multi-channel is planned, so the value is kept.
    repository = models.CharField(max_length=50)
    # Was ForeignKey(PerformanceFramework). Always "telemetry".
    framework = models.CharField(max_length=255)  # 2b: drop, and drop from the constraint

    # Was four ForeignKey(Push). The detector needs only revision and time from a push,
    # and the +/- 1 day dedup query has to stay relational, so both are denormalized.
    prev_push_revision = models.CharField(max_length=40)
    prev_push_timestamp = models.DateTimeField()
    push_revision = models.CharField(max_length=40)
    # Indexed because the dedup query now filters on it directly; it used to ride the
    # index on Push.time.
    push_timestamp = models.DateTimeField(db_index=True)
    original_push_revision = models.CharField(max_length=40, null=True, default=None)
    original_push_timestamp = models.DateTimeField(null=True, default=None)
    original_prev_push_revision = models.CharField(
        max_length=40, null=True, default=None
    )
    original_prev_push_timestamp = models.DateTimeField(null=True, default=None)

    manually_created = models.BooleanField(default=False)  # 2b: drop
    notes = models.TextField(null=True, blank=True)  # 2b: drop
    # Was ForeignKey(User), which is the only reason this table referenced auth at all.
    assignee_email = models.CharField(max_length=254, null=True, blank=True)  # 2b: drop
    sheriffed = models.BooleanField(default=True)  # 2b: drop

    # auto_now_add discards any value passed to create(); see the Phase 5 load.
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    triage_due_date = models.DateTimeField(null=True, default=None)  # 2b: drop
    first_triaged = models.DateTimeField(null=True, default=None)  # 2b: drop
    last_updated = models.DateTimeField(auto_now=True, null=True)  # 2b: drop

    # 2b: drop the summary status concept entirely, and roll it up in the API serializer
    # from the child alerts instead. Nothing writes this today, so every row is
    # UNTRIAGED; the members are carried over unchanged only so migrated values parse.
    UNTRIAGED = 0
    DOWNSTREAM = 1
    REASSIGNED = 2
    INVALID = 3
    IMPROVEMENT = 4
    INVESTIGATING = 5
    WONTFIX = 6
    FIXED = 7
    BACKED_OUT = 8
    INFRA = 9

    STATUSES = (
        (UNTRIAGED, "Untriaged"),
        (DOWNSTREAM, "Downstream"),
        (REASSIGNED, "Reassigned"),
        (INVALID, "Invalid"),
        (IMPROVEMENT, "Improvement"),
        (INVESTIGATING, "Investigating"),
        (WONTFIX, "Won't fix"),
        (FIXED, "Fixed"),
        (BACKED_OUT, "Backed out"),
        (INFRA, "Infra"),
    )

    status = models.IntegerField(choices=STATUSES, default=UNTRIAGED)  # 2b: drop

    # Telemetry keeps bug numbers on the alert, never on the summary.
    bug_number = models.PositiveIntegerField(null=True)  # 2b: drop
    bug_due_date = models.DateTimeField(null=True, default=None)  # 2b: drop
    bug_updated = models.DateTimeField(null=True)  # 2b: drop

    # Was ForeignKey(IssueTracker). This service is Bugzilla-only.
    issue_tracker = models.CharField(max_length=255, default="Bugzilla")  # 2b: drop

    # This field tells us if all bugs related to this summary were successfully
    # modified for group-based modifications.
    bugs_modified = models.BooleanField(default=True)

    class Meta:
        db_table = "performance_telemetry_alert_summary"
        constraints = [
            # 2b: drop framework from this constraint along with the column.
            models.UniqueConstraint(
                fields=["repository", "framework", "prev_push_revision", "push_revision"],
                name="unique_telemetry_alert_summary_push_range",
            )
        ]

    def __str__(self):
        return f"{self.framework} {self.repository} {self.prev_push_revision}-{self.push_revision}"


class PerformanceTelemetryAlert(models.Model):
    """
    A single telemetry alert.

    An individual "alert" that a probe's values have consistently changed level at a
    specific time. An alert is always a member of an alert summary.
    """

    id = models.AutoField(primary_key=True)
    summary = models.ForeignKey(
        PerformanceTelemetryAlertSummary, on_delete=models.CASCADE, related_name="alerts"
    )
    related_summary = models.ForeignKey(  # 2b: drop, telemetry has no reassignment flow
        PerformanceTelemetryAlertSummary,
        on_delete=models.CASCADE,
        related_name="related_alerts",
        null=True,
    )
    series_signature = models.ForeignKey(
        PerformanceTelemetrySignature, on_delete=models.CASCADE, related_name="alerts"
    )

    # Null when the probe's direction can't be determined (e.g. lower_is_better is unset)
    is_regression = models.BooleanField(null=True)
    starred = models.BooleanField(default=False)  # 2b: drop
    # Was ForeignKey(User).
    classifier_email = models.CharField(max_length=254, null=True, blank=True)  # 2b: drop
    sheriffed = models.BooleanField(default=True)  # 2b: drop

    # auto_now_add discards any value passed to create(); see the Phase 5 load.
    created = models.DateTimeField(auto_now_add=True, null=True)
    first_triaged = models.DateTimeField(null=True, default=None)  # 2b: drop
    last_updated = models.DateTimeField(auto_now=True, null=True)  # 2b: drop

    # A mirror of the Bugzilla resolution of this alert's bug, written by
    # ResolutionModifier. The members are carried over from Treeherder unchanged.
    # 2b: renumber so that no member is zero-valued.
    NEW = 0
    FIXED = 1
    INVALID = 2
    WONTFIX = 5
    INACTIVE = 3
    DUPLICATE = 4
    WORKSFORME = 6
    INCOMPLETE = 7
    MOVED = 8

    STATUSES = (
        (NEW, "NEW"),
        (FIXED, "FIXED"),
        (INVALID, "INVALID"),
        (WONTFIX, "WONTFIX"),
        (INACTIVE, "INACTIVE"),
        (DUPLICATE, "DUPLICATE"),
        (WORKSFORME, "WORKSFORME"),
        (INCOMPLETE, "INCOMPLETE"),
        (MOVED, "MOVED"),
    )

    status = models.IntegerField(choices=STATUSES, default=NEW)

    # 2b: drop both. They are percentages of the change in *sample count* rather than in
    # the metric, and nothing reads them.
    amount_pct = models.FloatField(help_text="Amount in percentage that series has changed")
    amount_abs = models.FloatField(help_text="Absolute amount that series has changed")
    # 2b: rename to prev_sample_count / new_sample_count, which is what these hold.
    prev_value = models.FloatField(help_text="Previous value of series before change")
    new_value = models.FloatField(help_text="New value of series after change")
    t_value = models.FloatField(  # 2b: drop
        help_text="t value out of analysis indicating confidence that change is 'real'",
        null=True,
    )

    confidence = models.FloatField(
        help_text=(
            "A value that indicates the confidence of the alert (specific to "
            "the detection method used)"
        ),
        null=True,
    )
    # 2b: rename to detection_technique and populate it from
    # probe.get_change_detection_technique(). Never written by telemetry today.
    detection_method = models.CharField(max_length=100, null=True)

    SKEWED = "SKEWED"
    OUTLIERS = "OUTLIERS"
    MODAL = "MODAL"
    OK = "OK"
    NA = "N/A"

    NOISE_PROFILES = (
        (SKEWED, "Samples are heavily found on one side of the mean."),
        (OUTLIERS, "There are more outliers than should be expected from a normal distribution."),
        (MODAL, "There are multiple areas where most values are found rather than only one."),
        (OK, "No issues were found."),
        (NA, "Could not compute a noise profile."),
    )

    noise_profile = models.CharField(  # 2b: drop, perf-specific
        max_length=30,
        choices=NOISE_PROFILES,
        default="N/A",
        help_text="The noise profile of the data which precedes this alert.",
    )

    manually_created = models.BooleanField(default=False)  # 2b: drop
    sustained = models.BooleanField(default=False)
    direction = models.CharField(max_length=100, null=True)

    prev_median = models.FloatField(
        help_text="Previous median value of series before change", default=0.0
    )
    new_median = models.FloatField(help_text="New median value of series after change", default=0.0)

    prev_p05 = models.FloatField(
        help_text="Previous P05 value of series before change", default=0.0
    )
    new_p05 = models.FloatField(help_text="New P05 value of series after change", default=0.0)

    prev_p95 = models.FloatField(
        help_text="Previous P95 value of series before change", default=0.0
    )
    new_p95 = models.FloatField(help_text="New P95 value of series after change", default=0.0)

    # Each alerting probe gets 1 bug, but we still want to group them together, so the
    # bug number lives on the alert rather than on the summary.
    bug_number = models.PositiveIntegerField(null=True)

    # This field tells us if the appropriate owners were already notified
    notified = models.BooleanField(default=False)

    # This field tells us if the bug was modified successfully for individual-based
    # modifications
    bug_modified = models.BooleanField(default=True)

    additional_data = models.JSONField(
        help_text=(
            "This field can be used to store additional data in JSON format that doesn't fit in "
            "any of the other fields. Custom CDP techniques can use this field to store extra "
            "non-standard data."
        ),
        default=dict,
    )

    class Meta:
        db_table = "performance_telemetry_alert"
        constraints = [
            models.UniqueConstraint(
                fields=["summary", "series_signature"],
                name="unique_telemetry_alert_per_summary",
            )
        ]

    def __str__(self):
        return f"{self.summary} {self.series_signature} {self.prev_median}->{self.new_median}"
