from datetime import UTC, datetime

import pytest
import requests
import responses

from mozbeacon.services.push import Push, PushNotFoundError, PushService

PUSH_URL = "https://treeherder.example/api/project/mozilla-central/push/"


@pytest.fixture
def push_service(settings):
    settings.TREEHERDER_API_URL = "https://treeherder.example/api"
    return PushService()


def push_payload(revision, timestamp):
    return {"revision": revision, "push_timestamp": timestamp}


@responses.activate
def test_get_push_returns_revision_and_time(push_service):
    responses.get(PUSH_URL, json={"results": [push_payload("abc123", 1769817600)]})

    push = push_service.get_push("mozilla-central", "abc123")

    assert push == Push(revision="abc123", time=datetime(2026, 1, 31, tzinfo=UTC))
    assert responses.calls[0].request.params["revision"] == "abc123"


@responses.activate
def test_a_user_agent_is_always_sent(push_service):
    """Treeherder's API answers 403 to the default requests User-Agent, so a push
    lookup without one fails for every revision, not just some."""
    responses.get(PUSH_URL, json={"results": [push_payload("abc123", 1769817600)]})

    push_service.get_push("mozilla-central", "abc123")

    user_agent = responses.calls[0].request.headers["User-Agent"]
    assert user_agent.startswith("mozbeacon/")
    assert "python-requests" not in user_agent


@responses.activate
def test_unknown_revision_raises(push_service):
    responses.get(PUSH_URL, json={"results": []})

    with pytest.raises(PushNotFoundError, match="nope"):
        push_service.get_push("mozilla-central", "nope")


@responses.activate
def test_an_api_error_propagates(push_service):
    """A Treeherder outage has to surface. The detector wraps each probe in a broad
    except, so a swallowed failure here would look like a probe with no detections."""
    responses.get(PUSH_URL, status=503)

    with pytest.raises(requests.HTTPError):
        push_service.get_push("mozilla-central", "abc123")


@responses.activate
def test_recent_pushes_are_newest_first(push_service):
    responses.get(
        PUSH_URL,
        json={"results": [push_payload("newer", 1769904000), push_payload("older", 1769817600)]},
    )

    pushes = push_service.get_recent_pushes("mozilla-central", count=2)

    assert [push.revision for push in pushes] == ["newer", "older"]
    assert pushes[0].time > pushes[1].time
    assert responses.calls[0].request.params["count"] == "2"
