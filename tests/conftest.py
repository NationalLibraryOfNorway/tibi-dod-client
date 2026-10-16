"""Shared fixtures: one `adapter` fixture parametrised over every adapter."""

from collections.abc import Iterator, Sequence

import pytest

from dod.domain.v1 import Announcement, ContentList, ContentMetadata, ContentResource
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

    def offer_catalog(
        self, lists: Sequence[ContentList], metadata: Sequence[ContentMetadata]
    ) -> None:
        self._service.offer_catalog(lists, metadata)

    def offer_resources(
        self,
        content_id: str,
        resources: Sequence[ContentResource],
        *,
        issued: bool = True,
    ) -> None:
        self._service.offer_resources(content_id, resources, issued=issued)

    def offer_file(self, path: str, body: bytes) -> None:
        self._service.offer_file(path, body)

    def file_url(self, path: str) -> str:
        return self._service.file_url(path)

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
