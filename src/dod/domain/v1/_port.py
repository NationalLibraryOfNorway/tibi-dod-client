"""The port towards a DODP v1 Service (ADR 0004)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from dod.domain.service import Password, Reply, SessionState
from dod.domain.v1._models import (
    Announcement,
    ContentList,
    ContentMetadata,
    ContentResources,
    ReadingSystemAttributes,
    ServiceAttributes,
)

type ResourceSink = Callable[[bytes], None]
"""Receives the body of a resource chunk by chunk, in order."""

type ByteRange = tuple[int, int | None]
"""First and last byte, both inclusive; `None` as last byte means to the end."""


class SinkRefused(Exception):
    """Raised by a `ResourceSink` to stop a transfer; the message says why.

    The port closes the connection and answers with a `Deviation`.
    """


class ServicePort(Protocol):
    """Synchronous, bound to one Service URL and at most one Session.

    Every method returns what the Service answered as a `Reply` and raises
    `TransportError` only when there was no usable answer. The port never logs
    in again and never retries (ADR 0005).
    """

    @property
    def session(self) -> SessionState | None:
        """The current Session, or `None` before a `log_on` has started one."""
        ...

    def resume(self, session: SessionState) -> None:
        """Continue a Session started by another port, from its `session` state.

        Sends nothing; whether the Service still knows the Session shows on the
        next call, as a `noActiveSession` fault when it does not.
        """
        ...

    def log_on(self, username: str, password: Password) -> Reply[bool]: ...

    def log_off(self) -> Reply[bool]: ...

    def get_service_attributes(self) -> Reply[ServiceAttributes]: ...

    def set_reading_system_attributes(
        self, attributes: ReadingSystemAttributes
    ) -> Reply[bool]: ...

    def get_service_announcements(self) -> Reply[tuple[Announcement, ...]]:
        """The announcements the user has not read yet (optional operation)."""
        ...

    def mark_announcements_as_read(self, ids: Sequence[str]) -> Reply[bool]:
        """Mark announcements as read; `false` means already read (optional)."""
        ...

    def get_content_list(
        self, id: str, first_item: int, last_item: int
    ) -> Reply[ContentList]:
        """A content list or a segment of it; `last_item` -1 means to the end.

        The id is sent as given, also when it is not an `xs:NMTOKEN`.
        """
        ...

    def get_content_metadata(self, content_id: str) -> Reply[ContentMetadata]:
        """The metadata of any content item, issued or not."""
        ...

    def get_content_resources(self, content_id: str) -> Reply[ContentResources]:
        """The files of issued content; anything else is an `invalidParameter`."""
        ...

    def fetch_resource(
        self, uri: str, sink: ResourceSink, byte_range: ByteRange | None = None
    ) -> Reply[int]:
        """GET `uri` (absolute) and stream the body to `sink`.

        `Ok.value` is the number of bytes given to the sink. Any 2xx status is
        `Ok` (206 only when a range was asked for) and every other status is a
        `Deviation`, with nothing given to the sink. The Exchange keeps the
        headers and the first 4 KiB of the body, marked truncated. The Session
        cookie is sent only to the Service's own origin; only userinfo in `uri`
        is used as credentials, and only towards that host. Redirects are not
        followed, and a failed GET never leads to a new login (ADR 0005).
        """
        ...

    def close(self) -> None:
        """Release the connection; the port is not used afterwards."""
        ...


class RawChannel(Protocol):
    """A narrower port for negative tests: it sends what it is given (ADR 0004).

    Where `ServicePort` builds a valid request for each operation, a
    `RawChannel` sends any operation name with any body, so a test can ask for
    something the specification forbids. Only the HTTP adapter implements it.
    Answers are classified as for `ServicePort`, and `TransportError` is raised
    only when there was no usable answer.
    """

    def send_raw(self, operation: str, body: str) -> Reply[str]:
        """Send `operation` with `body` as the content of the operation element.

        Nothing is checked or escaped: `body` is the XML text between the
        start and end tag of the operation element, in the DODP namespace.
        `Ok.value` is the answer's payload element as text.
        """
        ...

    def resume(self, session: SessionState) -> None:
        """Continue a Session started by a `ServicePort`; sends nothing."""
        ...

    def close(self) -> None:
        """Release the connection; the channel is not used afterwards."""
        ...
