import logging
from unittest.mock import Mock, patch

import pytest

from mozbeacon.detection.alert import (
    TelemetryAlertFactory,
)
from mozbeacon.detection.alert_manager import (
    TelemetryAlertManager,
)
from mozbeacon.model.models import PerformanceTelemetryAlert


@pytest.fixture
def mock_probes_dict(mock_probe):
    """Mock probes dictionary."""
    probes = {"test_probe": mock_probe}

    # Add indexed probes for tests that need them
    for i in range(10):
        probe = Mock()
        probe.name = f"test_probe_{i}"
        probe.should_file_bug.return_value = True
        probe.should_email.return_value = False
        probes[f"test_probe_{i}"] = probe

    return probes


@pytest.fixture
def mock_bug_manager():
    """Mock TelemetryBugManager."""
    manager = Mock()
    manager.file_bug.return_value = {"id": 123456}
    manager.modify_bug.return_value = None
    return manager


@pytest.fixture
def mock_email_manager():
    """Mock TelemetryEmailManager."""
    manager = Mock()
    manager.email_alert.return_value = None
    return manager


@pytest.fixture
def telemetry_alert_manager(mock_probes_dict):
    """TelemetryAlertManager instance with mocked dependencies."""
    with (
        patch("mozbeacon.detection.alert_manager.TelemetryBugManager") as mock_bug_mgr,
        patch("mozbeacon.detection.alert_manager.TelemetryEmailManager") as mock_email_mgr,
    ):
        mock_bug_mgr.return_value = Mock()
        mock_email_mgr.return_value = Mock()
        manager = TelemetryAlertManager(mock_probes_dict)
        return manager


@pytest.fixture
def telemetry_alert_with_probe(telemetry_alert_obj, test_telemetry_signature):
    """TelemetryAlert object with a probe set."""
    return telemetry_alert_obj


class TestTelemetryAlertManager:
    def test_initialization(self, mock_probes_dict):
        """Test TelemetryAlertManager initialization."""
        with (
            patch("mozbeacon.detection.alert_manager.TelemetryBugManager") as mock_bug_mgr,
            patch("mozbeacon.detection.alert_manager.TelemetryEmailManager") as mock_email_mgr,
        ):
            mock_bug_mgr.return_value = Mock()
            mock_email_mgr.return_value = Mock()

            manager = TelemetryAlertManager(mock_probes_dict)

            assert manager.probes == mock_probes_dict
            assert manager.bug_manager is not None
            assert manager.email_manager is not None

    def test_get_probe_info_success(self, telemetry_alert_manager, mock_probe):
        """Test getting probe info for a known probe."""
        probe = telemetry_alert_manager._get_probe_info("test_probe")
        assert probe == mock_probe

    def test_get_probe_info_unknown_probe(self, telemetry_alert_manager):
        """Test getting probe info for an unknown probe raises exception."""
        with pytest.raises(Exception) as exc_info:
            telemetry_alert_manager._get_probe_info("unknown_probe")

        assert "Unknown probe alerted" in str(exc_info.value)
        assert "unknown_probe" in str(exc_info.value)

    def test_comment_alert_bugs_does_nothing(self, telemetry_alert_manager, alert_without_bug):
        """Test comment_alert_bugs does nothing (pass statement)."""
        result = telemetry_alert_manager.comment_alert_bugs([alert_without_bug])
        assert result is None

    def test_update_alerts_no_updates(self, telemetry_alert_manager, alert_without_bug):
        """Test update_alerts when there are no updates."""
        with patch("mozbeacon.detection.alert_manager.TelemetryAlertModifier") as mock_modifier:
            mock_modifier.get_alert_updates.return_value = ({}, {})

            telemetry_alert_manager.update_alerts([alert_without_bug])

            mock_modifier.get_alert_updates.assert_called_once()

    def test_update_alerts_with_updates(self, telemetry_alert_manager, alert_without_bug, caplog):
        """Test update_alerts when there are updates to apply."""
        with patch("mozbeacon.detection.alert_manager.TelemetryAlertModifier") as mock_modifier:
            alert_id = str(alert_without_bug.telemetry_alert.id)
            mock_modifier.get_alert_updates.return_value = (
                {alert_id: {"status": 1}},
                {alert_id: alert_without_bug.telemetry_alert},
            )

            with caplog.at_level(logging.INFO):
                telemetry_alert_manager.update_alerts([alert_without_bug])

            # Verify the alert was updated
            alert_without_bug.telemetry_alert.refresh_from_db()
            assert alert_without_bug.telemetry_alert.status == 1

            # Verify logging
            assert "Updating the following alert IDs" in caplog.text
            assert str(alert_without_bug.telemetry_alert.id) in caplog.text
            assert "alerts updated with changes" in caplog.text

    def test_update_alerts_ignores_non_modifiable_fields(
        self, telemetry_alert_manager, alert_without_bug, caplog
    ):
        """Test update_alerts ignores fields not in MODIFIABLE_ALERT_FIELDS."""
        with patch("mozbeacon.detection.alert_manager.TelemetryAlertModifier") as mock_modifier:
            alert_id = str(alert_without_bug.telemetry_alert.id)
            mock_modifier.get_alert_updates.return_value = (
                {
                    alert_id: {
                        "status": 1,
                        "bug_number": 999999,  # Not in MODIFIABLE_ALERT_FIELDS
                    }
                },
                {alert_id: alert_without_bug.telemetry_alert},
            )

            telemetry_alert_manager.update_alerts([alert_without_bug])

            # Only status should be updated
            alert_without_bug.telemetry_alert.refresh_from_db()
            assert alert_without_bug.telemetry_alert.status == 1
            assert alert_without_bug.telemetry_alert.bug_number is None

    def test_modify_alert_bugs_disabled(self, telemetry_alert_manager, alert_without_bug):
        """Test modify_alert_bugs returns early (currently disabled)."""
        result = telemetry_alert_manager.modify_alert_bugs([alert_without_bug], [], [])
        assert result is None

    def test_should_file_bug_with_probe_that_should_file(
        self, telemetry_alert_manager, alert_without_bug, mock_probe
    ):
        """Test __should_file_bug returns True when conditions are met."""
        mock_probe.should_file_bug.return_value = True
        alert_without_bug.telemetry_alert.bug_number = None
        alert_without_bug.failed = False

        result = telemetry_alert_manager._TelemetryAlertManager__should_file_bug(
            mock_probe, alert_without_bug
        )

        assert result is True

    def test_should_file_bug_with_existing_bug(
        self, telemetry_alert_manager, alert_with_bug, mock_probe
    ):
        """Test __should_file_bug returns False when bug already exists."""
        mock_probe.should_file_bug.return_value = True
        alert_with_bug.failed = False

        result = telemetry_alert_manager._TelemetryAlertManager__should_file_bug(
            mock_probe, alert_with_bug
        )

        assert result is False

    def test_should_file_bug_with_failed_alert(
        self, telemetry_alert_manager, alert_without_bug, mock_probe
    ):
        """Test __should_file_bug returns False when alert has failed."""
        mock_probe.should_file_bug.return_value = True
        alert_without_bug.telemetry_alert.bug_number = None
        alert_without_bug.failed = True

        result = telemetry_alert_manager._TelemetryAlertManager__should_file_bug(
            mock_probe, alert_without_bug
        )

        assert result is False

    def test_should_file_bug_probe_should_not_file(
        self, telemetry_alert_manager, alert_without_bug, mock_probe
    ):
        """Test __should_file_bug returns False when probe should not file bug."""
        mock_probe.should_file_bug.return_value = False
        alert_without_bug.telemetry_alert.bug_number = None
        alert_without_bug.failed = False

        result = telemetry_alert_manager._TelemetryAlertManager__should_file_bug(
            mock_probe, alert_without_bug
        )

        assert result is False

    def test_file_alert_bug_success(self, telemetry_alert_manager, alert_without_bug, mock_probe):
        """Test _file_alert_bug successfully files a bug."""
        mock_probe.should_file_bug.return_value = True
        telemetry_alert_manager.bug_manager.file_bug.return_value = {"id": 123456}
        alert_without_bug.telemetry_signature.probe = "test_probe"

        bug_id = telemetry_alert_manager._file_alert_bug(alert_without_bug)

        assert bug_id == 123456
        alert_without_bug.telemetry_alert.refresh_from_db()
        assert alert_without_bug.telemetry_alert.bug_number == 123456
        telemetry_alert_manager.bug_manager.file_bug.assert_called_once()

    def test_file_alert_bug_when_should_not_file(
        self, telemetry_alert_manager, alert_without_bug, mock_probe
    ):
        """Test _file_alert_bug returns None when should not file bug."""
        mock_probe.should_file_bug.return_value = False
        alert_without_bug.telemetry_signature.probe = "test_probe"

        bug_id = telemetry_alert_manager._file_alert_bug(alert_without_bug)

        assert bug_id is None
        telemetry_alert_manager.bug_manager.file_bug.assert_not_called()

    def test_file_alert_bug_failure_deletes_alert(
        self, telemetry_alert_manager, alert_without_bug, mock_probe, caplog
    ):
        """Test _file_alert_bug deletes alert on failure."""
        mock_probe.should_file_bug.return_value = True
        telemetry_alert_manager.bug_manager.file_bug.side_effect = Exception("Bugzilla API error")
        alert_without_bug.telemetry_signature.probe = "test_probe"
        alert_id = alert_without_bug.telemetry_alert.id

        with caplog.at_level(logging.WARNING):
            bug_id = telemetry_alert_manager._file_alert_bug(alert_without_bug)

        assert bug_id is None
        assert alert_without_bug.failed is True
        assert "Failed to create alert bug" in caplog.text

        # Verify the alert was deleted
        assert not PerformanceTelemetryAlert.objects.filter(id=alert_id).exists()

    def test_file_alert_bug_attaches_attachment(
        self, telemetry_alert_manager, alert_without_bug, mock_probe
    ):
        """Test _file_alert_bug calls attach for each attachment in optional_detection_info."""
        mock_probe.should_file_bug.return_value = True
        telemetry_alert_manager.bug_manager.file_bug.return_value = {"id": 123456}
        alert_without_bug.telemetry_signature.probe = "test_probe"
        attachment = {
            "data": "base64encodedcontent==",
            "content_type": "application/json",
            "file_name": "results.json",
            "summary": "Detection results",
        }
        alert_without_bug.optional_detection_info = {"attachments": [attachment]}

        bug_id = telemetry_alert_manager._file_alert_bug(alert_without_bug)

        assert bug_id == 123456
        telemetry_alert_manager.bug_manager.attach.assert_called_once_with(123456, attachment)

    def test_file_alert_bug_attach_failure_does_not_fail_bug_filing(
        self, telemetry_alert_manager, alert_without_bug, mock_probe, caplog
    ):
        """Test _file_alert_bug still returns the bug ID when attaching an attachment fails."""
        mock_probe.should_file_bug.return_value = True
        telemetry_alert_manager.bug_manager.file_bug.return_value = {"id": 123456}
        telemetry_alert_manager.bug_manager.attach.side_effect = Exception("Attach failed")
        alert_without_bug.telemetry_signature.probe = "test_probe"
        alert_without_bug.optional_detection_info = {
            "attachments": [
                {
                    "data": "abc",
                    "content_type": "text/plain",
                    "file_name": "f.txt",
                    "summary": "s",
                }
            ]
        }

        with caplog.at_level(logging.WARNING):
            bug_id = telemetry_alert_manager._file_alert_bug(alert_without_bug)

        assert bug_id == 123456
        assert "Failed to attach an attachment" in caplog.text
        alert_without_bug.telemetry_alert.refresh_from_db()
        assert alert_without_bug.telemetry_alert.bug_number == 123456

    def test_should_notify_with_probe_that_should_email(
        self, telemetry_alert_manager, alert_without_bug, mock_probe
    ):
        """Test __should_notify returns True when conditions are met."""
        mock_probe.should_email.return_value = True
        alert_without_bug.telemetry_alert.bug_number = None
        alert_without_bug.failed = False

        result = telemetry_alert_manager._TelemetryAlertManager__should_notify(
            mock_probe, alert_without_bug
        )

        assert result is True

    def test_should_notify_with_existing_bug(
        self, telemetry_alert_manager, alert_with_bug, mock_probe
    ):
        """Test __should_notify returns False when bug already exists."""
        mock_probe.should_email.return_value = True
        alert_with_bug.failed = False

        result = telemetry_alert_manager._TelemetryAlertManager__should_notify(
            mock_probe, alert_with_bug
        )

        assert result is False

    def test_should_notify_with_failed_alert(
        self, telemetry_alert_manager, alert_without_bug, mock_probe
    ):
        """Test __should_notify returns False when alert has failed."""
        mock_probe.should_email.return_value = True
        alert_without_bug.telemetry_alert.bug_number = None
        alert_without_bug.failed = True

        result = telemetry_alert_manager._TelemetryAlertManager__should_notify(
            mock_probe, alert_without_bug
        )

        assert result is False

    def test_should_notify_probe_should_not_email(
        self, telemetry_alert_manager, alert_without_bug, mock_probe
    ):
        """Test __should_notify returns False when probe should not email."""
        mock_probe.should_email.return_value = False
        alert_without_bug.telemetry_alert.bug_number = None
        alert_without_bug.failed = False

        result = telemetry_alert_manager._TelemetryAlertManager__should_notify(
            mock_probe, alert_without_bug
        )

        assert result is False

    def test_email_alert_success(self, telemetry_alert_manager, alert_without_bug, mock_probe):
        """Test _email_alert successfully sends an email."""
        mock_probe.should_email.return_value = True
        alert_without_bug.telemetry_signature.probe = "test_probe"

        telemetry_alert_manager._email_alert(alert_without_bug)

        alert_without_bug.telemetry_alert.refresh_from_db()
        assert alert_without_bug.telemetry_alert.notified is True
        telemetry_alert_manager.email_manager.email_alert.assert_called_once()

    def test_email_alert_when_should_not_notify(
        self, telemetry_alert_manager, alert_without_bug, mock_probe
    ):
        """Test _email_alert returns early when should not notify."""
        mock_probe.should_email.return_value = False
        alert_without_bug.telemetry_signature.probe = "test_probe"

        telemetry_alert_manager._email_alert(alert_without_bug)

        telemetry_alert_manager.email_manager.email_alert.assert_not_called()

    def test_email_alert_failure_sets_notified_false(
        self, telemetry_alert_manager, alert_without_bug, mock_probe, caplog
    ):
        """Test _email_alert sets notified=False on failure."""
        mock_probe.should_email.return_value = True
        telemetry_alert_manager.email_manager.email_alert.side_effect = Exception(
            "Email sending error"
        )
        alert_without_bug.telemetry_signature.probe = "test_probe"

        with caplog.at_level(logging.WARNING):
            telemetry_alert_manager._email_alert(alert_without_bug)

        alert_without_bug.telemetry_alert.refresh_from_db()
        assert alert_without_bug.telemetry_alert.notified is False
        assert "Failed to create alert email" in caplog.text

    def test_redo_email_alerts(
        self, test_telemetry_alert, telemetry_alert_manager, mock_probe, caplog
    ):
        """Test _redo_email_alerts retries failed email alerts."""
        mock_probe.should_email.return_value = True

        with caplog.at_level(logging.INFO):
            telemetry_alert_manager._redo_email_alerts()

        assert "House keeping: retrying emails for alerts" in caplog.text
        # The email_manager.email_alert should be called for the retry
        telemetry_alert_manager.email_manager.email_alert.assert_called()

    def test_redo_email_alerts_skips_with_bug_number(self, telemetry_alert_manager, alert_with_bug):
        """Test _redo_email_alerts skips alerts with bug numbers."""
        alert_with_bug.telemetry_alert.notified = False
        alert_with_bug.telemetry_alert.save()

        telemetry_alert_manager._redo_email_alerts()

        # Should not be called because alert has a bug number
        telemetry_alert_manager.email_manager.email_alert.assert_not_called()

    def test_redo_email_alerts_skips_already_notified(
        self, telemetry_alert_manager, alert_without_bug
    ):
        """Test _redo_email_alerts skips alerts already notified."""
        alert_without_bug.telemetry_alert.notified = True
        alert_without_bug.telemetry_alert.bug_number = None
        alert_without_bug.telemetry_alert.save()

        telemetry_alert_manager._redo_email_alerts()

        # Should not be called because alert is already notified
        telemetry_alert_manager.email_manager.email_alert.assert_not_called()

    def test_redo_email_alerts_marks_notified_when_probe_no_longer_alerting(
        self, create_telemetry_signature, create_telemetry_alert, telemetry_alert_manager
    ):
        """Test _redo_email_alerts marks alert notified when its probe is no longer in probes."""
        signature = create_telemetry_signature(probe="removed_probe")
        alert_row = create_telemetry_alert(signature, notified=False)

        telemetry_alert_manager._redo_email_alerts()

        alert_row.refresh_from_db()
        assert alert_row.notified is True
        telemetry_alert_manager.email_manager.email_alert.assert_not_called()

    def test_redo_bug_modifications(
        self, telemetry_alert_manager, test_telemetry_alert_summary, caplog
    ):
        """Test _redo_bug_modifications retries failed bug modifications."""
        test_telemetry_alert_summary.bugs_modified = False
        test_telemetry_alert_summary.save()

        with caplog.at_level(logging.INFO):
            telemetry_alert_manager._redo_bug_modifications()

        assert "House keeping: retrying bug modifications" in caplog.text

    def test_redo_bug_modifications_no_unmodified_summaries(
        self, telemetry_alert_manager, test_telemetry_alert_summary, caplog
    ):
        """Test _redo_bug_modifications when all summaries are modified."""
        test_telemetry_alert_summary.bugs_modified = True
        test_telemetry_alert_summary.save()

        with caplog.at_level(logging.INFO):
            telemetry_alert_manager._redo_bug_modifications()

        assert "House keeping: retrying bug modifications" in caplog.text

    def test_redo_bug_modifications_with_alerts(
        self, telemetry_alert_manager, test_telemetry_alert_summary, alert_without_bug, caplog
    ):
        """Test _redo_bug_modifications reconstructs alerts from unmodified summaries."""
        test_telemetry_alert_summary.bugs_modified = False
        test_telemetry_alert_summary.save()

        with caplog.at_level(logging.INFO):
            telemetry_alert_manager._redo_bug_modifications()

        assert "House keeping: retrying bug modifications" in caplog.text
        # This test ensures line 244 is covered (alert construction in loop)

    def test_redo_bug_modifications_marks_modified_when_probe_no_longer_alerting(
        self,
        create_telemetry_signature,
        create_telemetry_alert,
        test_telemetry_alert_summary,
        telemetry_alert_manager,
    ):
        """Test _redo_bug_modifications marks summary/alert modified when probe is no longer alerting."""
        test_telemetry_alert_summary.bugs_modified = False
        test_telemetry_alert_summary.save()

        signature = create_telemetry_signature(probe="removed_probe")
        alert_row = create_telemetry_alert(signature, bug_number=123456, bug_modified=False)

        with patch(
            "mozbeacon.detection.alert_manager.TelemetryAlertManager.modify_alert_bugs"
        ) as mock_modify:
            telemetry_alert_manager._redo_bug_modifications()

        alert_row.refresh_from_db()
        test_telemetry_alert_summary.refresh_from_db()
        assert alert_row.bug_modified is True
        assert test_telemetry_alert_summary.bugs_modified is True
        # Alert with unknown probe must not be passed to modify_alert_bugs
        alerts_passed = mock_modify.call_args[0][0]
        assert alert_row.id not in [a.telemetry_alert.id for a in alerts_passed]

    def test_house_keeping_calls_all_methods(
        self, telemetry_alert_manager, alert_without_bug, caplog
    ):
        """Test house_keeping calls both _redo_email_alerts and _redo_bug_modifications."""
        alert_without_bug.telemetry_alert.notified = False
        alert_without_bug.telemetry_alert.bug_number = None
        alert_without_bug.telemetry_alert.save()

        with caplog.at_level(logging.INFO):
            telemetry_alert_manager.house_keeping([alert_without_bug], [], [])

        assert "Performing house keeping" in caplog.text
        assert "House keeping: retrying emails for alerts" in caplog.text
        assert "House keeping: retrying bug modifications" in caplog.text
        assert "House keeping: rechecking is_regression for alerts" in caplog.text

    def test_recheck_is_regression_corrects_stale_value(
        self,
        create_telemetry_signature,
        create_telemetry_alert,
        telemetry_alert_manager,
        mock_probe,
    ):
        """Test _recheck_is_regression updates is_regression when it no longer matches settings."""
        mock_probe.lower_is_better = True

        signature = create_telemetry_signature(probe="test_probe")
        # Stored as an improvement, but the confidence + lower_is_better say regression
        alert_row = create_telemetry_alert(signature, is_regression=False, confidence=0.95)

        telemetry_alert_manager._recheck_is_regression()

        alert_row.refresh_from_db()
        assert alert_row.is_regression is True

    def test_recheck_is_regression_leaves_correct_value(
        self,
        create_telemetry_signature,
        create_telemetry_alert,
        telemetry_alert_manager,
        mock_probe,
    ):
        """Test _recheck_is_regression leaves is_regression alone when it already matches."""
        mock_probe.lower_is_better = True

        signature = create_telemetry_signature(probe="test_probe")
        alert_row = create_telemetry_alert(signature, is_regression=True, confidence=0.95)

        telemetry_alert_manager._recheck_is_regression()

        alert_row.refresh_from_db()
        assert alert_row.is_regression is True

    def test_recheck_is_regression_skips_unknown_probe(
        self, create_telemetry_signature, create_telemetry_alert, telemetry_alert_manager
    ):
        """Test _recheck_is_regression ignores alerts whose probe is no longer alerting."""
        signature = create_telemetry_signature(probe="removed_probe")
        alert_row = create_telemetry_alert(signature, is_regression=False, confidence=0.95)

        telemetry_alert_manager._recheck_is_regression()

        alert_row.refresh_from_db()
        # Unchanged because the probe is not in the manager's probes
        assert alert_row.is_regression is False

    def test_multiple_alerts_bulk_update(
        self,
        create_telemetry_signature,
        create_telemetry_alert,
        telemetry_alert_manager,
        test_telemetry_alert_summary,
    ):
        """Test update_alerts performs bulk updates for multiple alerts."""

        # Create multiple alerts with different signatures to avoid unique constraint
        alerts = []
        for i in range(3):
            signature = create_telemetry_signature(probe=f"test_probe_{i}")
            alert_row = create_telemetry_alert(signature)
            alerts.append(TelemetryAlertFactory.construct_alert(alert_row))

        with patch("mozbeacon.detection.alert_manager.TelemetryAlertModifier") as mock_modifier:
            alert_updates = {
                str(alerts[0].telemetry_alert.id): {"status": 1},
                str(alerts[1].telemetry_alert.id): {"status": 2},
                str(alerts[2].telemetry_alert.id): {"status": 1},
            }
            alerts_with_updates = {
                str(alerts[0].telemetry_alert.id): alerts[0].telemetry_alert,
                str(alerts[1].telemetry_alert.id): alerts[1].telemetry_alert,
                str(alerts[2].telemetry_alert.id): alerts[2].telemetry_alert,
            }
            mock_modifier.get_alert_updates.return_value = (alert_updates, alerts_with_updates)

            telemetry_alert_manager.update_alerts(alerts)

            # Verify all alerts were updated
            for i, alert in enumerate(alerts):
                alert.telemetry_alert.refresh_from_db()
                expected_status = 1 if i in [0, 2] else 2
                assert alert.telemetry_alert.status == expected_status

    def test_manage_alerts_full_workflow(
        self, test_telemetry_alert, telemetry_alert_manager, mock_probe
    ):
        """Test manage_alerts runs the full workflow successfully."""

        # Create test alerts
        alert = TelemetryAlertFactory.construct_alert(test_telemetry_alert)

        # Configure mocks
        mock_probe.should_file_bug.return_value = True
        mock_probe.should_email.return_value = False
        telemetry_alert_manager.bug_manager.file_bug.return_value = {"id": 999888}

        with patch("mozbeacon.detection.alert_manager.TelemetryAlertModifier") as mock_modifier:
            mock_modifier.get_alert_updates.return_value = ({}, {})

            # Run the full manage_alerts workflow
            telemetry_alert_manager.manage_alerts([alert])

            # Verify all steps were executed
            mock_modifier.get_alert_updates.assert_called_once()
            telemetry_alert_manager.bug_manager.file_bug.assert_called_once()

            # Verify the bug was filed
            test_telemetry_alert.refresh_from_db()
            assert test_telemetry_alert.bug_number == 999888

    def test_manage_alerts_continues_after_update_failure(
        self, telemetry_alert_manager, alert_without_bug, mock_probe, caplog
    ):
        """Test manage_alerts continues after update_alerts fails."""
        mock_probe.should_file_bug.return_value = True
        alert_without_bug.telemetry_signature.probe = "test_probe"

        telemetry_alert_manager.bug_manager.file_bug.return_value = {"id": 111222}

        with patch("mozbeacon.detection.alert_manager.TelemetryAlertModifier") as mock_modifier:
            mock_modifier.get_alert_updates.side_effect = Exception("Update error")

            with caplog.at_level(logging.INFO):
                telemetry_alert_manager.manage_alerts([alert_without_bug])

            # Verify update failed but filing still happened
            assert "Failed to update alerts" in caplog.text
            telemetry_alert_manager.bug_manager.file_bug.assert_called_once()

            # Bug should still be filed
            alert_without_bug.telemetry_alert.refresh_from_db()
            assert alert_without_bug.telemetry_alert.bug_number == 111222

    def test_manage_alerts_continues_after_file_bug_failure(
        self, telemetry_alert_manager, alert_without_bug, mock_probe, caplog
    ):
        """Test manage_alerts continues after _file_alert_bug fails."""
        mock_probe.should_file_bug.return_value = True
        mock_probe.should_email.return_value = False
        alert_without_bug.telemetry_signature.probe = "test_probe"

        # Make file_bug fail
        telemetry_alert_manager.bug_manager.file_bug.side_effect = Exception("Bugzilla error")

        with patch("mozbeacon.detection.alert_manager.TelemetryAlertModifier") as mock_modifier:
            mock_modifier.get_alert_updates.return_value = ({}, {})

            with caplog.at_level(logging.INFO):
                telemetry_alert_manager.manage_alerts([alert_without_bug])

            # Verify bug filing failed but housekeeping still ran
            assert "Failed to create alert bug" in caplog.text
            assert "Performing house keeping" in caplog.text

    def test_manage_alerts_continues_after_email_failure(
        self, telemetry_alert_manager, alert_without_bug, mock_probe, caplog
    ):
        """Test manage_alerts continues after _email_alert fails."""
        mock_probe.should_file_bug.return_value = False
        mock_probe.should_email.return_value = True
        alert_without_bug.telemetry_signature.probe = "test_probe"
        alert_without_bug.telemetry_signature.save()

        # Make email_alert fail
        telemetry_alert_manager.email_manager.email_alert.side_effect = Exception("Email error")

        with patch("mozbeacon.detection.alert_manager.TelemetryAlertModifier") as mock_modifier:
            mock_modifier.get_alert_updates.return_value = ({}, {})

            with caplog.at_level(logging.INFO):  # Changed to INFO to capture house keeping log
                telemetry_alert_manager.manage_alerts([alert_without_bug])

            # Verify email failed but housekeeping still ran
            assert "Failed to create alert email" in caplog.text
            assert "Performing house keeping" in caplog.text

            # Verify notified was set to False
            alert_without_bug.telemetry_alert.refresh_from_db()
            assert alert_without_bug.telemetry_alert.notified is False

    def test_manage_alerts_filters_failed_alerts_before_modify(
        self, create_telemetry_signature, create_telemetry_alert, telemetry_alert_manager
    ):
        """Test manage_alerts filters out failed alerts before modify_alert_bugs."""

        # Create alerts (probes already exist in telemetry_alert_manager via fixture)
        alerts = []
        for i in range(3):
            signature = create_telemetry_signature(probe=f"test_probe_{i}")
            alert_row = create_telemetry_alert(signature)
            alerts.append(TelemetryAlertFactory.construct_alert(alert_row))

        # Mark some alerts as failed during bug filing
        def file_bug_side_effect(probe, alert):
            if alert == alerts[0] or alert == alerts[2]:
                raise Exception("Bug filing failed")
            return {"id": 999777}

        telemetry_alert_manager.bug_manager.file_bug.side_effect = file_bug_side_effect

        with patch("mozbeacon.detection.alert_manager.TelemetryAlertModifier") as mock_modifier:
            mock_modifier.get_alert_updates.return_value = ({}, {})

            # Create a spy on modify_alert_bugs to verify which alerts are passed
            original_modify = telemetry_alert_manager.modify_alert_bugs
            modify_calls = []

            def modify_spy(alerts_arg, commented_bugs, new_bugs):
                modify_calls.append(alerts_arg)
                return original_modify(alerts_arg, commented_bugs, new_bugs)

            telemetry_alert_manager.modify_alert_bugs = modify_spy

            telemetry_alert_manager.manage_alerts(alerts)

            # Verify modify_alert_bugs was called (could be multiple times due to house_keeping)
            # Find the call with non-empty alerts
            non_empty_calls = [call for call in modify_calls if len(call) > 0]
            assert len(non_empty_calls) >= 1, (
                "modify_alert_bugs should be called with at least one non-empty alert list"
            )

            # Check the first non-empty call (the main manage_alerts call)
            passed_alerts = non_empty_calls[0]
            # Only the middle alert (index 1) should be passed (others failed)
            assert len(passed_alerts) == 1, f"Expected 1 alert, got {len(passed_alerts)}"
            assert passed_alerts[0] == alerts[1]

    def test_redo_bug_modifications_with_mixed_bug_numbers(
        self,
        create_telemetry_signature,
        create_telemetry_alert,
        test_telemetry_alert_summary,
        telemetry_alert_manager,
        caplog,
    ):
        """Test _redo_bug_modifications with alert summary containing alerts with mixed bug numbers.

        Verifies that calls made to the TelemetryAlertManager.modify_alert_bugs method contain
        only alerts that have bugs.
        """
        # Mark the alert summary as not modified to trigger _redo_bug_modifications
        test_telemetry_alert_summary.bugs_modified = False
        test_telemetry_alert_summary.save()

        # Create alert 1 WITH a bug number
        sig1 = create_telemetry_signature(probe="test_probe_1")
        alert_row_1 = create_telemetry_alert(sig1, bug_number=123456, bug_modified=True)
        TelemetryAlertFactory.construct_alert(alert_row_1)

        # Create alert 2 WITHOUT a bug number
        sig2 = create_telemetry_signature(probe="test_probe_2")
        alert_row_2 = create_telemetry_alert(sig2, bug_number=None, bug_modified=True)
        TelemetryAlertFactory.construct_alert(alert_row_2)

        # Create alert 3 WITH a bug number
        sig3 = create_telemetry_signature(probe="test_probe_3")
        alert_row_3 = create_telemetry_alert(sig3, bug_number=654321, bug_modified=True)
        TelemetryAlertFactory.construct_alert(alert_row_3)

        # Mock modify_alert_bugs to check if we call it with only alerts that have bugs
        with patch(
            "mozbeacon.detection.alert_manager.TelemetryAlertManager.modify_alert_bugs"
        ) as mock_modify_alert_bugs:
            with caplog.at_level(logging.INFO):
                telemetry_alert_manager._redo_bug_modifications()

            # Verify that the modify_alert_bugs method is only called with 2 alerts
            alerts_to_modify = mock_modify_alert_bugs.call_args_list[0][0][0]
            assert len(alerts_to_modify) == 2

            # Verify that the alerts are only those with the bugs from above
            for bug_number in (123456, 654321):
                assert bug_number in [
                    alert.telemetry_alert.bug_number for alert in alerts_to_modify
                ]

    def test_manage_alerts_with_mixed_bug_and_email_alerts(
        self,
        create_telemetry_signature,
        create_telemetry_alert,
        telemetry_alert_manager,
        test_telemetry_alert_summary,
    ):
        """Test manage_alerts with some alerts filing bugs and others sending emails."""

        # Create two probes with different configurations
        probe_with_bug = Mock()
        probe_with_bug.name = "probe_bug"
        probe_with_bug.should_file_bug.return_value = True
        probe_with_bug.should_email.return_value = False

        probe_with_email = Mock()
        probe_with_email.name = "probe_email"
        probe_with_email.should_file_bug.return_value = False
        probe_with_email.should_email.return_value = True

        # Update the manager's probes dictionary
        telemetry_alert_manager.probes = {
            "probe_bug": probe_with_bug,
            "probe_email": probe_with_email,
        }

        # Create alerts
        sig1 = create_telemetry_signature(probe="probe_bug")
        alert_row1 = create_telemetry_alert(sig1)
        alert1 = TelemetryAlertFactory.construct_alert(alert_row1)

        sig2 = create_telemetry_signature(probe="probe_email")
        alert_row2 = create_telemetry_alert(sig2)
        alert2 = TelemetryAlertFactory.construct_alert(alert_row2)

        telemetry_alert_manager.bug_manager.file_bug.return_value = {"id": 333444}

        with patch("mozbeacon.detection.alert_manager.TelemetryAlertModifier") as mock_modifier:
            mock_modifier.get_alert_updates.return_value = ({}, {})

            telemetry_alert_manager.manage_alerts([alert1, alert2])

            # Verify bug was filed for alert1
            alert_row1.refresh_from_db()
            assert alert_row1.bug_number == 333444

            # Verify email was sent for alert2
            alert_row2.refresh_from_db()
            assert alert_row2.notified is True
            assert alert_row2.bug_number is None

            # Verify the correct methods were called
            telemetry_alert_manager.bug_manager.file_bug.assert_called_once()
            telemetry_alert_manager.email_manager.email_alert.assert_called_once()


class TestEmailLimiting:
    """Tests for email limiting functionality."""

    def test_emails_left_never_negative(self, telemetry_alert_manager):
        """Test emails_left() returns 0 when limit exceeded, never negative."""
        from mozbeacon.detection.utils import (
            EMAIL_LIMIT,
        )

        # Exceed the limit
        for _ in range(EMAIL_LIMIT + 10):
            telemetry_alert_manager._email_made()

        # Should return 0, not a negative number
        assert telemetry_alert_manager._emails_left() == 0

    def test_email_alert_respects_limit(
        self, telemetry_alert_manager, alert_without_bug, mock_probe
    ):
        """Test _email_alert returns early when email limit is reached."""
        from mozbeacon.detection.utils import (
            EMAIL_LIMIT,
        )

        mock_probe.should_email.return_value = True
        alert_without_bug.telemetry_signature.probe = "test_probe"

        # Use up all emails
        telemetry_alert_manager._emails_made = EMAIL_LIMIT

        # Try to send an email
        telemetry_alert_manager._email_alert(alert_without_bug)

        # Email manager should not be called
        telemetry_alert_manager.email_manager.email_alert.assert_not_called()

        # Alert should not be marked as notified
        alert_without_bug.telemetry_alert.refresh_from_db()
        assert alert_without_bug.telemetry_alert.notified is False

    def test_email_alert_when_one_email_left(
        self, telemetry_alert_manager, alert_without_bug, mock_probe
    ):
        """Test _email_alert works when exactly one email remains."""
        from mozbeacon.detection.utils import (
            EMAIL_LIMIT,
        )

        mock_probe.should_email.return_value = True
        alert_without_bug.telemetry_signature.probe = "test_probe"

        # Use up all but one email
        telemetry_alert_manager._emails_made = EMAIL_LIMIT - 1

        # Send the last email
        telemetry_alert_manager._email_alert(alert_without_bug)

        # Email should be sent
        telemetry_alert_manager.email_manager.email_alert.assert_called_once()

        # Counter should be incremented
        assert telemetry_alert_manager._emails_made == EMAIL_LIMIT

        # Alert should be marked as notified
        alert_without_bug.telemetry_alert.refresh_from_db()
        assert alert_without_bug.telemetry_alert.notified is True

    def test_email_limit_prevents_multiple_alerts(
        self, create_telemetry_signature, create_telemetry_alert, telemetry_alert_manager
    ):
        """Test that email limit prevents emails after limit is reached across multiple alerts."""
        from mozbeacon.detection.utils import (
            EMAIL_LIMIT,
        )

        # Create probes and alerts
        telemetry_alert_manager.probes = {}
        alerts = []
        for i in range(5):
            probe = Mock()
            probe.name = f"email_probe_{i}"
            probe.should_file_bug.return_value = False
            probe.should_email.return_value = True
            telemetry_alert_manager.probes[probe.name] = probe

            signature = create_telemetry_signature(probe=probe.name)
            alert_row = create_telemetry_alert(signature)
            alerts.append(TelemetryAlertFactory.construct_alert(alert_row))

        # Set email count to near the limit
        telemetry_alert_manager._emails_made = EMAIL_LIMIT - 2

        # Process all alerts
        for alert in alerts:
            telemetry_alert_manager._email_alert(alert)

        # Only 2 emails should have been sent
        assert telemetry_alert_manager.email_manager.email_alert.call_count == 2
        assert telemetry_alert_manager._emails_made == EMAIL_LIMIT

        # Check which alerts were notified
        alerts[0].telemetry_alert.refresh_from_db()
        alerts[1].telemetry_alert.refresh_from_db()
        alerts[2].telemetry_alert.refresh_from_db()
        alerts[3].telemetry_alert.refresh_from_db()
        alerts[4].telemetry_alert.refresh_from_db()

        assert alerts[0].telemetry_alert.notified is True
        assert alerts[1].telemetry_alert.notified is True
        assert alerts[2].telemetry_alert.notified is False
        assert alerts[3].telemetry_alert.notified is False
        assert alerts[4].telemetry_alert.notified is False

    def test_email_limit_with_failures(
        self, create_telemetry_signature, create_telemetry_alert, telemetry_alert_manager
    ):
        """Test that email counter increments even when email sending fails."""

        # Create a probe that should email
        probe = Mock()
        probe.name = "email_probe"
        probe.should_file_bug.return_value = False
        probe.should_email.return_value = True
        telemetry_alert_manager.probes = {"email_probe": probe}

        # Create an alert
        signature = create_telemetry_signature(probe="email_probe")
        alert_row = create_telemetry_alert(signature)
        alert = TelemetryAlertFactory.construct_alert(alert_row)

        # Make email_alert raise an exception
        telemetry_alert_manager.email_manager.email_alert.side_effect = Exception("Email error")

        initial_count = telemetry_alert_manager._emails_made

        # Process the alert
        telemetry_alert_manager._email_alert(alert)

        # Counter should NOT be incremented because the email failed before _email_made() was called
        assert telemetry_alert_manager._emails_made == initial_count

        # Alert should not be marked as notified
        alert.telemetry_alert.refresh_from_db()
        assert alert.telemetry_alert.notified is False

    def test_redo_email_alerts_respects_limit(
        self, create_telemetry_signature, create_telemetry_alert, telemetry_alert_manager
    ):
        """Test _redo_email_alerts respects the email limit."""
        from mozbeacon.detection.utils import (
            EMAIL_LIMIT,
        )

        # Create probes and alerts that need emails
        telemetry_alert_manager.probes = {}
        for i in range(10):
            probe = Mock()
            probe.name = f"email_probe_{i}"
            probe.should_file_bug.return_value = False
            probe.should_email.return_value = True
            telemetry_alert_manager.probes[probe.name] = probe

            signature = create_telemetry_signature(probe=probe.name)
            create_telemetry_alert(signature)

        # Set email count to near the limit
        telemetry_alert_manager._emails_made = EMAIL_LIMIT - 3

        # Run redo emails
        telemetry_alert_manager._redo_email_alerts()

        # Only 3 emails should have been sent (respecting the limit)
        assert telemetry_alert_manager.email_manager.email_alert.call_count == 3
        assert telemetry_alert_manager._emails_made == EMAIL_LIMIT

    def test_email_limit_boundary_at_zero(
        self, telemetry_alert_manager, alert_without_bug, mock_probe
    ):
        """Test email limiting at exactly zero emails left."""
        from mozbeacon.detection.utils import (
            EMAIL_LIMIT,
        )

        mock_probe.should_email.return_value = True
        alert_without_bug.telemetry_signature.probe = "test_probe"

        # Set to exactly at limit
        telemetry_alert_manager._emails_made = EMAIL_LIMIT
        assert telemetry_alert_manager._emails_left() == 0

        # Try to send email
        telemetry_alert_manager._email_alert(alert_without_bug)

        # Should not send
        telemetry_alert_manager.email_manager.email_alert.assert_not_called()

    def test_email_counter_persists_across_operations(
        self, create_telemetry_signature, create_telemetry_alert, telemetry_alert_manager
    ):
        """Test that email counter persists correctly across different operations."""
        # Create probes that should email
        telemetry_alert_manager.probes = {}

        # Send 5 emails through _email_alert
        for i in range(5):
            probe = Mock()
            probe.name = f"email_probe_{i}"
            probe.should_file_bug.return_value = False
            probe.should_email.return_value = True
            telemetry_alert_manager.probes[probe.name] = probe

            signature = create_telemetry_signature(probe=probe.name)
            alert_row = create_telemetry_alert(signature)
            alert = TelemetryAlertFactory.construct_alert(alert_row)
            telemetry_alert_manager._email_alert(alert)

        assert telemetry_alert_manager._emails_made == 5

        # Create more unnotified alerts for redo
        for i in range(5, 8):
            probe = Mock()
            probe.name = f"email_probe_{i}"
            probe.should_file_bug.return_value = False
            probe.should_email.return_value = True
            telemetry_alert_manager.probes[probe.name] = probe

            signature = create_telemetry_signature(probe=probe.name)
            create_telemetry_alert(signature)

        # Run redo emails
        telemetry_alert_manager._redo_email_alerts()

        # Should now have 8 total emails sent (5 + 3)
        assert telemetry_alert_manager._emails_made == 8


class TestOutboundKillSwitches:
    """TELEMETRY_ENABLE_BUGS and TELEMETRY_ENABLE_EMAILS gate everything that leaves the
    service, and nothing that doesn't. This is what lets the new service run against a
    copy of the migrated database while Treeherder is still the one filing bugs.
    """

    @pytest.fixture
    def bug_filing_alert(self, telemetry_alert_obj, mock_probes_dict):
        """An alert whose probe wants a bug filed, with no bug yet."""
        probe = mock_probes_dict["test_probe"]
        probe.should_file_bug.return_value = True
        probe.should_email.return_value = False
        telemetry_alert_obj.telemetry_signature.probe = "test_probe"
        telemetry_alert_obj.telemetry_alert.bug_number = None
        telemetry_alert_obj.telemetry_alert.save()
        return telemetry_alert_obj

    @pytest.fixture
    def emailing_alert(self, telemetry_alert_obj, mock_probes_dict):
        """An alert whose probe wants an email, not a bug."""
        probe = mock_probes_dict["test_probe"]
        probe.should_file_bug.return_value = False
        probe.should_email.return_value = True
        telemetry_alert_obj.telemetry_signature.probe = "test_probe"
        telemetry_alert_obj.telemetry_alert.bug_number = None
        telemetry_alert_obj.telemetry_alert.notified = False
        telemetry_alert_obj.telemetry_alert.save()
        return telemetry_alert_obj

    def test_bugs_off_files_nothing(self, telemetry_alert_manager, bug_filing_alert, settings):
        settings.TELEMETRY_ENABLE_BUGS = False

        telemetry_alert_manager._file_alert_bug(bug_filing_alert)

        telemetry_alert_manager.bug_manager.file_bug.assert_not_called()
        bug_filing_alert.telemetry_alert.refresh_from_db()
        assert bug_filing_alert.telemetry_alert.bug_number is None

    def test_bugs_off_skips_the_alert_instead_of_failing_it(
        self, telemetry_alert_manager, bug_filing_alert, settings
    ):
        """The gate must not look like a filing failure. _file_alert_bug deletes the
        alert row when filing raises, which during a shadow run would empty the table
        and read as a catastrophic port bug rather than a disabled switch.
        """
        settings.TELEMETRY_ENABLE_BUGS = False
        alert_id = bug_filing_alert.telemetry_alert.id

        telemetry_alert_manager._file_alert_bug(bug_filing_alert)

        assert PerformanceTelemetryAlert.objects.filter(id=alert_id).exists()
        assert not getattr(bug_filing_alert, "failed", False)

    def test_bugs_on_still_files(self, telemetry_alert_manager, bug_filing_alert, settings):
        settings.TELEMETRY_ENABLE_BUGS = True
        telemetry_alert_manager.bug_manager.file_bug.return_value = {"id": 999}

        telemetry_alert_manager._file_alert_bug(bug_filing_alert)

        telemetry_alert_manager.bug_manager.file_bug.assert_called_once()
        bug_filing_alert.telemetry_alert.refresh_from_db()
        assert bug_filing_alert.telemetry_alert.bug_number == 999

    def test_bugs_off_writes_no_see_also_but_marks_modified(
        self, telemetry_alert_manager, bug_filing_alert, settings
    ):
        """Same contract as the email path. Bugzilla is untouched, and the rows are
        marked so house keeping stops retrying them.
        """
        settings.TELEMETRY_ENABLE_BUGS = False
        bug_filing_alert.telemetry_alert.bug_number = 12345
        bug_filing_alert.telemetry_alert.bug_modified = False
        bug_filing_alert.telemetry_alert.save()
        summary = bug_filing_alert.telemetry_alert_summary
        summary.bugs_modified = False
        summary.save()

        with patch("mozbeacon.detection.alert_manager.TelemetryBugModifier") as modifier:
            modifier.get_bug_modifications.return_value = {12345: {"see_also": ["999"]}}
            telemetry_alert_manager.modify_alert_bugs([bug_filing_alert], [], [])

        telemetry_alert_manager.bug_manager.modify_bug.assert_not_called()
        summary.refresh_from_db()
        bug_filing_alert.telemetry_alert.refresh_from_db()
        assert summary.bugs_modified is True
        assert bug_filing_alert.telemetry_alert.bug_modified is True

    def test_emails_off_sends_nothing_but_marks_notified(
        self, telemetry_alert_manager, emailing_alert, settings
    ):
        """notified is set anyway, so the alert does not sit in a backlog that would
        flush all at once against the 50 email cap when emails are switched back on.
        The tradeoff is that alerts detected while the switch is off never get one.
        """
        settings.TELEMETRY_ENABLE_EMAILS = False

        telemetry_alert_manager._email_alert(emailing_alert)

        telemetry_alert_manager.email_manager.email_alert.assert_not_called()
        emailing_alert.telemetry_alert.refresh_from_db()
        assert emailing_alert.telemetry_alert.notified is True

    def test_emails_off_does_not_consume_the_email_budget(
        self, telemetry_alert_manager, emailing_alert, settings
    ):
        """Nothing was sent, so the rate limit counter must not move."""
        settings.TELEMETRY_ENABLE_EMAILS = False
        before = telemetry_alert_manager._emails_left()

        telemetry_alert_manager._email_alert(emailing_alert)

        assert telemetry_alert_manager._emails_left() == before

    def test_emails_on_still_sends(self, telemetry_alert_manager, emailing_alert, settings):
        settings.TELEMETRY_ENABLE_EMAILS = True

        telemetry_alert_manager._email_alert(emailing_alert)

        telemetry_alert_manager.email_manager.email_alert.assert_called_once()
        emailing_alert.telemetry_alert.refresh_from_db()
        assert emailing_alert.telemetry_alert.notified is True

    def test_email_retries_drain_the_backlog_without_sending(
        self, telemetry_alert_manager, emailing_alert, settings
    ):
        """House keeping still runs with emails off. It marks the pending alerts done
        rather than leaving them to accumulate, which is the point of marking notified
        at the call site instead of bailing out of the whole stage.
        """
        settings.TELEMETRY_ENABLE_EMAILS = False

        telemetry_alert_manager._redo_email_alerts()

        telemetry_alert_manager.email_manager.email_alert.assert_not_called()
        emailing_alert.telemetry_alert.refresh_from_db()
        assert emailing_alert.telemetry_alert.notified is True

    def test_bug_modification_retries_drain_without_touching_bugzilla(
        self,
        telemetry_alert_manager,
        test_telemetry_alert_summary,
        create_telemetry_signature,
        create_telemetry_alert,
        mock_probe,
        settings,
    ):
        """The mirror of the above for _redo_bug_modifications.

        Two alerts under one summary, both with bugs, which is what makes
        SeeAlsoModifier produce real modifications to retry. A single alert has nothing
        to link to and so produces none, guard or no guard.
        """
        settings.TELEMETRY_ENABLE_BUGS = False
        test_telemetry_alert_summary.bugs_modified = False
        test_telemetry_alert_summary.save()

        rows = []
        for name, bug in (("probe_one", 111), ("probe_two", 222)):
            signature = create_telemetry_signature(probe=name)
            telemetry_alert_manager.probes[name] = mock_probe
            rows.append(create_telemetry_alert(signature, bug_number=bug, bug_modified=False))

        telemetry_alert_manager._redo_bug_modifications()

        telemetry_alert_manager.bug_manager.modify_bug.assert_not_called()

        # Only the bugs that actually received a see_also change are marked. The group
        # flag on the summary is the one house keeping filters on, so that is what has
        # to clear for the retry to stop.
        test_telemetry_alert_summary.refresh_from_db()
        assert test_telemetry_alert_summary.bugs_modified is True
        for row in rows:
            row.refresh_from_db()
        assert any(row.bug_modified for row in rows)

    def test_bugzilla_resolution_sync_stays_live(self, telemetry_alert_manager, settings):
        """update_alerts reads Bugzilla and writes only locally. Gating it would stop the
        shadow database tracking resolutions while Treeherder keeps tracking them, which
        turns the migrated backlog into pure noise in the cutover diff.
        """
        settings.TELEMETRY_ENABLE_BUGS = False
        settings.TELEMETRY_ENABLE_EMAILS = False

        with patch("mozbeacon.detection.alert_manager.TelemetryAlertModifier") as modifier:
            modifier.get_alert_updates.return_value = ({}, {})
            telemetry_alert_manager.update_alerts([])

        modifier.get_alert_updates.assert_called_once()

    def test_is_regression_recheck_stays_live(
        self, telemetry_alert_manager, emailing_alert, mock_probe, settings
    ):
        """Also local-only, so it runs regardless of the switches."""
        settings.TELEMETRY_ENABLE_BUGS = False
        settings.TELEMETRY_ENABLE_EMAILS = False

        # This stage rebuilds alerts from rows, so the probe has to be registered under
        # the signature name that is actually stored.
        signature = emailing_alert.telemetry_signature
        mock_probe.lower_is_better = True
        telemetry_alert_manager.probes = {signature.probe: mock_probe}

        # lower_is_better with a positive confidence is a regression, so the stored
        # False is stale and has to be corrected.
        emailing_alert.telemetry_alert.is_regression = False
        emailing_alert.telemetry_alert.confidence = 0.9
        emailing_alert.telemetry_alert.save()

        telemetry_alert_manager._recheck_is_regression()

        emailing_alert.telemetry_alert.refresh_from_db()
        assert emailing_alert.telemetry_alert.is_regression is True
