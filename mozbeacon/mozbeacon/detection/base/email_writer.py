"""
This module intends to be a delegate for writing emails.

Copied from Treeherder's treeherder/perf/email.py, trimmed to the Email dataclass and
the EmailWriter base that the telemetry writer subclasses. The backfill, deletion and
perf-alert writers that made up the rest of that module stayed behind with the perf
sheriffing they serve.

Its clients should only instantiate their writer of choice &
provide it with some basic data to include in the email.
They then get an email that's ready-to-send via taskcluster.Notify service.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)


@dataclass
class Email:
    address: str = None
    content: str = None
    subject: str = None

    def as_payload(self) -> dict:
        return asdict(self)


class EmailWriter(ABC):
    def __init__(self):
        self._email = Email()

    def prepare_new_email(self, must_mention: list[object] | object) -> dict:
        """
        Template method
        """
        must_mention = self.__ensure_its_list(must_mention)

        self._write_address()
        self._write_subject()
        self._write_content(must_mention)
        return self.email

    @property
    def email(self):
        return self._email.as_payload()

    @abstractmethod
    def _write_address(self):
        pass  # pragma: no cover

    @abstractmethod
    def _write_subject(self):
        pass  # pragma: no cover

    @abstractmethod
    def _write_content(self, must_mention: list[object]):
        pass  # pragma: no cover

    @staticmethod
    def __ensure_its_list(must_mention) -> list[object]:
        if not isinstance(must_mention, list):
            must_mention = [must_mention]
        return must_mention
