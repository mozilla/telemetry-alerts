"""Push metadata.

The detector needs exactly two fields per push: its revision and the time it landed.
Treeherder owns that data and this service has no replica of it, so it is read over
Treeherder's HTTP API. Everything else about a push (jobs, commits, authors) is
irrelevant here.

Access is behind a single get_push() so that swapping the API for a read replica is a
one-file change.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class PushNotFoundError(Exception):
    """Raised when a revision has no push in the given repository."""


@dataclass(frozen=True)
class Push:
    """The push fields the detector and the bug/email content actually use.

    Deliberately not a model. Pushes live in Treeherder, and the summary carries the
    revision and timestamp it needs denormalized onto its own row.
    """

    revision: str
    time: datetime


class PushService:
    def __init__(self, api_url=None, timeout=None):
        self.api_url = (api_url or settings.TREEHERDER_API_URL).rstrip("/")
        self.timeout = timeout or settings.TREEHERDER_API_TIMEOUT
        # Treeherder's API answers 403 to the default requests User-Agent, so the
        # service has to identify itself. Every push lookup fails without this.
        self.user_agent = f"mozbeacon/{settings.SITE_HOSTNAME}"

    def get_push(self, repository: str, revision: str) -> Push:
        results = self._query(repository, {"revision": revision})
        if not results:
            raise PushNotFoundError(f"No push for revision {revision} in {repository}")
        return self._to_push(results[0])

    def get_recent_pushes(self, repository: str, count: int = 2) -> list[Push]:
        """Most recent pushes first. Only used by the test-alert commands, which need a
        realistic push range to hang a test bug or email off."""
        return [self._to_push(push) for push in self._query(repository, {"count": count})]

    def _query(self, repository: str, params: dict) -> list[dict]:
        url = f"{self.api_url}/project/{repository}/push/"
        response = requests.get(
            url,
            params=params,
            timeout=self.timeout,
            headers={"User-Agent": self.user_agent},
        )
        response.raise_for_status()
        return response.json().get("results", [])

    @staticmethod
    def _to_push(push: dict) -> Push:
        return Push(
            revision=push["revision"],
            time=datetime.fromtimestamp(push["push_timestamp"], tz=UTC),
        )
