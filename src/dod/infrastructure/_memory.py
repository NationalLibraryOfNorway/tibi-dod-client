"""An in-memory Service and the port adapter towards it (ADR 0003).

Behaves like a small conforming Service without any wire: users, Sessions and
one-shot injected faults and deviations. The HTTP adapter's fake Service on
localhost behaves the same, and both are held to the same contract tests.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import replace

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
    Announcement,
    ContentList,
    ContentMetadata,
    ReadingSystemAttributes,
    ServiceAttributes,
    operation_ref,
)


class InMemoryService:
    """The state of one in-memory Service; ports opened on it share it."""

    def __init__(self, attributes: ServiceAttributes | None = None) -> None:
        self._users: dict[str, str] = {}
        self._sessions: set[str] = set()
        self._injected: dict[str, Fault | str] = {}
        self._announcements: tuple[Announcement, ...] = ()
        self._read: set[str] = set()
        self._lists: dict[str, ContentList] = {}
        self._metadata: dict[str, ContentMetadata] = {}
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

    def offer_catalog(
        self, lists: Sequence[ContentList], metadata: Sequence[ContentMetadata]
    ) -> None:
        """Publish content lists by id and book metadata by identifier."""
        self._lists = {item.id: item for item in lists}
        self._metadata = {item.identifier or "": item for item in metadata}

    def expire_sessions(self) -> None:
        """End every Session on the Service, as if they had all timed out."""
        self._sessions.clear()

    def inject_deviation(self, operation: str) -> None:
        """Make the next call of `operation` answer contrary to the specification."""
        self._injected[operation] = "deviation"

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

    def close(self) -> None:
        """Nothing to release."""

    def _active(self) -> bool:
        return self._token is not None and self._token in self._service._sessions


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
