"""An in-memory Service and the port adapter towards it (ADR 0003).

Behaves like a small conforming Service without any wire: users, Sessions and
one-shot injected faults and deviations. The HTTP adapter's fake Service on
localhost behaves the same, and both are held to the same contract tests.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import replace
from xml.sax.saxutils import escape

from dod.domain.service import (
    Deviation,
    Exchange,
    Fault,
    FaultKind,
    Ok,
    Password,
    Reply,
    SessionState,
)
from dod.domain.v1 import (
    SPEC_REFS,
    Announcement,
    BookmarkSet,
    ByteRange,
    ContentList,
    ContentMetadata,
    ContentResource,
    ContentResources,
    KeyExchangeObject,
    ReadingSystemAttributes,
    ResourceSink,
    ServiceAttributes,
    SinkRefused,
    operation_ref,
)
from dod.infrastructure._bookmarks import bookmark_set, parse_for_sending


class InMemoryService:
    """The state of one in-memory Service; ports opened on it share it."""

    def __init__(self, attributes: ServiceAttributes | None = None) -> None:
        self._users: dict[str, str] = {}
        self._sessions: set[str] = set()
        self._injected: dict[str, Fault | str] = {}
        self._false: set[str] = set()
        self._announcements: tuple[Announcement, ...] = ()
        self._read: set[str] = set()
        self._lists: dict[str, ContentList] = {}
        self._metadata: dict[str, ContentMetadata] = {}
        self._resources: dict[str, tuple[ContentResources, bool]] = {}
        self._files: dict[str, bytes] = {}
        self._bookmarks: dict[str, str] = {}
        self._key_exchange: dict[str, str] = {}
        self.attributes = attributes or ServiceAttributes(
            service_provider_id="synthetic-provider",
            service_id="synthetic-service",
            supported_content_selection_methods=("BROWSE",),
            supports_server_side_back=False,
            supports_search=False,
            supported_uplink_audio_codecs=(),
            supports_audio_labels=False,
            supported_optional_operations=(),
        )

    def add_user(self, username: str, password: str) -> None:
        self._users[username] = password

    def inject_fault(self, operation: str, kind: str, reason: str) -> None:
        """Make the next call of `operation` answer with the fault `kind`."""
        exchange = _exchange(operation)
        self._injected[operation] = Fault(
            kind=FaultKind(kind), reason=reason, exchange=exchange
        )

    def offer_announcements(self, *announcements: Announcement) -> None:
        """Publish announcements and declare the two optional operations."""
        self._announcements = announcements
        self._read = set()
        operations = {
            *self.attributes.supported_optional_operations,
            "SERVICE_ANNOUNCEMENTS",
        }
        self.attributes = replace(
            self.attributes, supported_optional_operations=tuple(sorted(operations))
        )

    def declare_operations(self, *tokens: str) -> None:
        """Declare optional operations in `supportedOptionalOperations`."""
        operations = {*self.attributes.supported_optional_operations, *tokens}
        self.attributes = replace(
            self.attributes, supported_optional_operations=tuple(sorted(operations))
        )

    def offer_bookmarks(self, content_id: str, bookmark_set: str) -> None:
        """Store the bookmark set of a book (a `bookmarkSet` document)."""
        self._bookmarks[content_id] = bookmark_set

    def offer_key_exchange(self, key_name: str, key_exchange: str) -> None:
        """Answer `getKeyExchangeObject` for `key_name` with this element."""
        self._key_exchange[key_name] = key_exchange

    def offer_catalog(
        self, lists: Sequence[ContentList], metadata: Sequence[ContentMetadata]
    ) -> None:
        """Publish content lists by id and book metadata by identifier."""
        self._lists = {item.id: item for item in lists}
        self._metadata = {item.identifier or "": item for item in metadata}

    def offer_resources(
        self,
        content_id: str,
        resources: Sequence[ContentResource],
        *,
        issued: bool = True,
    ) -> None:
        """Publish the files of a book; unless `issued` they are not available."""
        self._resources[content_id] = (ContentResources(tuple(resources)), issued)

    def offer_file(self, path: str, body: bytes) -> None:
        """Serve `body` at `file_url(path)`."""
        self._files[path] = body

    def file_url(self, path: str) -> str:
        return f"{_FILE_PREFIX}{path}"

    def expire_sessions(self) -> None:
        """End every Session on the Service, as if they had all timed out."""
        self._sessions.clear()

    def inject_deviation(self, operation: str) -> None:
        """Make the next call of `operation` answer contrary to the specification."""
        self._injected[operation] = "deviation"

    def inject_false(self, operation: str) -> None:
        """Make the next call of `operation` answer `false`."""
        self._false.add(operation)

    def open_port(self) -> InMemoryPort:
        return InMemoryPort(self)

    # -- used by the port -------------------------------------------------

    def _take_injected(self, operation: str) -> Reply[bool] | None:
        injected = self._injected.pop(operation, None)
        if injected is None:
            return None
        if isinstance(injected, Fault):
            return injected
        return Deviation(
            description=f"{operation} answered with something other than a response",
            spec_reference=operation_ref(operation),
            exchange=_exchange(operation),
        )


_FILE_PREFIX = "https://memory.example.org/"
_BODY_KEPT = 4096


def _exchange(operation: str) -> Exchange:
    return Exchange(
        method="POST",
        url="memory://service",
        request_headers=(),
        request_body=operation,
        status=200,
        response_headers=(),
        response_body="",
    )


class InMemoryPort:
    """A `ServicePort` bound to one `InMemoryService` and at most one Session."""

    def __init__(self, service: InMemoryService) -> None:
        self._service = service
        self._token: str | None = None

    @property
    def session(self) -> SessionState | None:
        if self._token is None:
            return None
        return SessionState(cookies=(("session", self._token),))

    def resume(self, session: SessionState) -> None:
        self._token = dict(session.cookies).get("session")

    def log_on(self, username: str, password: Password) -> Reply[bool]:
        injected = self._service._take_injected("logOn")
        if injected is not None:
            return injected
        if self._service._users.get(username) != password.reveal():
            return Ok(value=False, exchange=_exchange("logOn"))
        self._token = secrets.token_hex(8)
        self._service._sessions.add(self._token)
        return Ok(value=True, exchange=_exchange("logOn"))

    def log_off(self) -> Reply[bool]:
        injected = self._service._take_injected("logOff")
        if injected is not None:
            return injected
        ended = self._token in self._service._sessions
        self._service._sessions.discard(self._token or "")
        return Ok(value=ended, exchange=_exchange("logOff"))

    def get_service_attributes(self) -> Reply[ServiceAttributes]:
        injected = self._service._take_injected("getServiceAttributes")
        if injected is not None:
            assert not isinstance(injected, Ok)
            return injected
        if not self._active():
            return _no_active_session("getServiceAttributes")
        return Ok(
            value=self._service.attributes,
            exchange=_exchange("getServiceAttributes"),
        )

    def set_reading_system_attributes(
        self, attributes: ReadingSystemAttributes
    ) -> Reply[bool]:
        injected = self._service._take_injected("setReadingSystemAttributes")
        if injected is not None:
            return injected
        if not self._active():
            return _no_active_session("setReadingSystemAttributes")
        return Ok(value=True, exchange=_exchange("setReadingSystemAttributes"))

    def get_service_announcements(self) -> Reply[tuple[Announcement, ...]]:
        injected = self._service._take_injected("getServiceAnnouncements")
        if injected is not None:
            assert not isinstance(injected, Ok)
            return injected
        if not self._active():
            return _no_active_session("getServiceAnnouncements")
        if not self._service._announcements:
            return _not_supported("getServiceAnnouncements")
        unread = tuple(
            a for a in self._service._announcements if a.id not in self._service._read
        )
        return Ok(value=unread, exchange=_exchange("getServiceAnnouncements"))

    def mark_announcements_as_read(self, ids: Sequence[str]) -> Reply[bool]:
        injected = self._service._take_injected("markAnnouncementsAsRead")
        if injected is not None:
            return injected
        if not self._active():
            return _no_active_session("markAnnouncementsAsRead")
        if not self._service._announcements:
            return _not_supported("markAnnouncementsAsRead")
        known = {a.id for a in self._service._announcements}
        if not set(ids) <= known:
            return Fault(
                kind=FaultKind.INVALID_PARAMETER,
                reason="unknown announcement",
                exchange=_exchange("markAnnouncementsAsRead"),
            )
        fresh = set(ids) - self._service._read
        self._service._read |= fresh
        return Ok(value=bool(fresh), exchange=_exchange("markAnnouncementsAsRead"))

    def get_content_list(
        self, id: str, first_item: int, last_item: int
    ) -> Reply[ContentList]:
        injected = self._service._take_injected("getContentList")
        if injected is not None:
            assert not isinstance(injected, Ok)
            return injected
        if not self._active():
            return _no_active_session("getContentList")
        exchange = _exchange("getContentList")
        known = self._service._lists.get(id)
        if known is None and id == "issued":
            known = ContentList(id="issued", total_items=0)
        if known is None:
            return Fault(
                kind=FaultKind.INVALID_PARAMETER,
                reason="unknown list",
                exchange=exchange,
            )
        total = len(known.items)
        end = total - 1 if last_item == -1 else last_item
        if first_item < 0 or first_item >= total or end < first_item:
            return Ok(
                value=replace(known, items=(), first_item=None, last_item=None),
                exchange=exchange,
            )
        end = min(end, total - 1)
        return Ok(
            value=replace(
                known,
                items=known.items[first_item : end + 1],
                first_item=first_item,
                last_item=end,
            ),
            exchange=exchange,
        )

    def get_content_metadata(self, content_id: str) -> Reply[ContentMetadata]:
        injected = self._service._take_injected("getContentMetadata")
        if injected is not None:
            assert not isinstance(injected, Ok)
            return injected
        if not self._active():
            return _no_active_session("getContentMetadata")
        exchange = _exchange("getContentMetadata")
        known = self._service._metadata.get(content_id)
        if known is None:
            return Fault(
                kind=FaultKind.INVALID_PARAMETER,
                reason="unknown content",
                exchange=exchange,
            )
        return Ok(value=known, exchange=exchange)

    def issue_content(self, content_id: str) -> Reply[bool]:
        return self._lend("issueContent", content_id, issued=True)

    def return_content(self, content_id: str) -> Reply[bool]:
        reply = self._lend("returnContent", content_id, issued=False)
        if isinstance(reply, Ok) and reply.value is False:
            return Deviation(
                description="returnContentResult is false; the specification "
                "allows only true or a fault",
                spec_reference=operation_ref("returnContent"),
                exchange=reply.exchange,
            )
        return reply

    def _lend(self, operation: str, content_id: str, *, issued: bool) -> Reply[bool]:
        injected = self._service._take_injected(operation)
        if injected is not None:
            return injected
        if not self._active():
            return _no_active_session(operation)
        exchange = _exchange(operation)
        known = self._service._resources.get(content_id)
        if known is None and content_id not in self._service._metadata:
            return Fault(
                kind=FaultKind.INVALID_PARAMETER,
                reason="unknown content",
                exchange=exchange,
            )
        files = known[0] if known is not None else ContentResources(())
        self._service._resources[content_id] = (files, issued)
        if operation in self._service._false:
            self._service._false.discard(operation)
            return Ok(value=False, exchange=exchange)
        return Ok(value=True, exchange=exchange)

    def get_bookmarks(self, content_id: str) -> Reply[BookmarkSet]:
        found = self._bookmark_precheck("getBookmarks", content_id)
        if isinstance(found, (Fault, Deviation)):
            return found
        stored = self._service._bookmarks.get(content_id) or (
            '<bookmarkSet xmlns="http://www.daisy.org/z3986/2005/bookmark/">'
            f"<title><text/></title><uid>{escape(content_id)}</uid></bookmarkSet>"
        )
        return Ok(
            value=bookmark_set(parse_for_sending(stored)),
            exchange=found,
        )

    def set_bookmarks(self, content_id: str, bookmark_set: str) -> Reply[bool]:
        parse_for_sending(bookmark_set)
        found = self._bookmark_precheck("setBookmarks", content_id)
        if isinstance(found, (Fault, Deviation)):
            return found
        self._service._bookmarks[content_id] = bookmark_set
        return Ok(value=True, exchange=found)

    def _bookmark_precheck(
        self, operation: str, content_id: str
    ) -> Exchange | Fault | Deviation:
        injected = self._service._take_injected(operation)
        if injected is not None:
            assert not isinstance(injected, Ok)
            return injected
        if not self._active():
            return _no_active_session(operation)
        exchange = _exchange(operation)
        if (
            content_id not in self._service._resources
            and content_id not in self._service._metadata
        ):
            return Fault(
                kind=FaultKind.INVALID_PARAMETER,
                reason="unknown content",
                exchange=exchange,
            )
        return exchange

    def get_key_exchange_object(
        self, requested_key_name: str
    ) -> Reply[KeyExchangeObject]:
        injected = self._service._take_injected("getKeyExchangeObject")
        if injected is not None:
            assert not isinstance(injected, Ok)
            return injected
        if not self._active():
            return _no_active_session("getKeyExchangeObject")
        exchange = _exchange("getKeyExchangeObject")
        known = self._service._key_exchange.get(requested_key_name)
        if known is None:
            return Fault(
                kind=FaultKind.INVALID_PARAMETER,
                reason="unknown key",
                exchange=exchange,
            )
        return Ok(value=KeyExchangeObject(xml=known), exchange=exchange)

    def get_content_resources(self, content_id: str) -> Reply[ContentResources]:
        injected = self._service._take_injected("getContentResources")
        if injected is not None:
            assert not isinstance(injected, Ok)
            return injected
        if not self._active():
            return _no_active_session("getContentResources")
        exchange = _exchange("getContentResources")
        known = self._service._resources.get(content_id)
        if known is None or not known[1]:
            return Fault(
                kind=FaultKind.INVALID_PARAMETER,
                reason="content is not issued",
                exchange=exchange,
            )
        return Ok(value=known[0], exchange=exchange)

    def fetch_resource(
        self, uri: str, sink: ResourceSink, byte_range: ByteRange | None = None
    ) -> Reply[int]:
        body = (
            self._service._files.get(uri.removeprefix(_FILE_PREFIX))
            if uri.startswith(_FILE_PREFIX)
            else None
        )
        if body is None:
            return self._answered(uri, 404, b"not found", None)
        status = 200
        if byte_range is not None:
            first, last = byte_range
            body = body[first : None if last is None else last + 1]
            status = 206
        try:
            sink(body)
        except SinkRefused as refusal:
            return Deviation(
                description=f"the transfer was stopped: {refusal}",
                spec_reference=SPEC_REFS["type.resources"],
                exchange=_resource_exchange(uri, status, body),
            )
        return self._answered(uri, status, body, len(body))

    def _answered(
        self, uri: str, status: int, body: bytes, delivered: int | None
    ) -> Reply[int]:
        exchange = _resource_exchange(uri, status, body)
        if delivered is None:
            return Deviation(
                description=f"the resource answered HTTP {status}",
                spec_reference=SPEC_REFS["type.resources"],
                exchange=exchange,
            )
        return Ok(value=delivered, exchange=exchange)

    def close(self) -> None:
        """Nothing to release."""

    def _active(self) -> bool:
        return self._token is not None and self._token in self._service._sessions


def _resource_exchange(uri: str, status: int, body: bytes) -> Exchange:
    return Exchange(
        method="GET",
        url=uri,
        request_headers=(),
        request_body="",
        status=status,
        response_headers=(),
        response_body=body[:_BODY_KEPT].decode("utf-8", errors="replace"),
        response_truncated=len(body) > _BODY_KEPT,
    )


def _no_active_session(operation: str) -> Fault:
    return Fault(
        kind=FaultKind.NO_ACTIVE_SESSION,
        reason="no active session",
        exchange=_exchange(operation),
    )


def _not_supported(operation: str) -> Fault:
    return Fault(
        kind=FaultKind.OPERATION_NOT_SUPPORTED,
        reason="not supported",
        exchange=_exchange(operation),
    )
