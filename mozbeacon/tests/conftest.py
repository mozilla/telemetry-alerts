import pytest


@pytest.fixture
def mock_bugfiler_settings(monkeypatch):
    """Bugzilla credentials for the tests that exercise the bug path.

    Both keys are set deliberately: the filer key creates bugs, the commenter key
    writes see_also and attachments, and a test that only set the first would pass
    against a service that can't modify anything.
    """
    for name, value in (
        ("BUGFILER_API_URL", "https://bugzilla.mozilla.org"),
        ("BUGFILER_API_KEY", "test-api-key"),
        ("COMMENTER_API_KEY", "test-commenter-key"),
        ("SITE_HOSTNAME", "alerts.telemetry.moz.tools"),
    ):
        monkeypatch.setattr(f"mozbeacon.detection.base.bug_manager.settings.{name}", value)
