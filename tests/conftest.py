"""Shared fixtures: one `adapter` fixture parametrised over every adapter."""

from collections.abc import Iterator

import pytest

from dod.domain.v1 import Announcement
from dod.infrastructure import InMemoryService
from support import Harness, HttpHarness


class _MemoryHarness:
    def __init__(self) -> None:
        self._service = InMemoryService()

    def add_user(self, username: str, password: str) -> None:
        self._service.add_user(username, password)

    def inject_fault(self, operation: str, kind: str, reason: str) -> None:
        self._service.inject_fault(operation, kind, reason)

    def inject_deviation(self, operation: str) -> None:
        self._service.inject_deviation(operation)

    def offer_announcements(self, *announcements: Announcement) -> None:
        self._service.offer_announcements(*announcements)

    def open_port(self):  # type: ignore[no-untyped-def]
        return self._service.open_port()


@pytest.fixture
def http_harness() -> Iterator[HttpHarness]:
    harness = HttpHarness()
    yield harness
    harness.close()


@pytest.fixture(params=["memory", "http"])
def adapter(request: pytest.FixtureRequest) -> Iterator[Harness]:
    if request.param == "memory":
        yield _MemoryHarness()
    else:
        harness = HttpHarness()
        yield harness
        harness.close()
