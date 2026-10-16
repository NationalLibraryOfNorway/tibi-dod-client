"""A minimal DODP v1 Service on localhost, for the tests only (ADR 0003).

It speaks SOAP 1.1 document/literal over HTTP, validates every request and
every response document it builds itself against the local schema copies and
records what it received. Faults, deviations and transport failures are
injected per operation and used once. Documents that break the schemas on
purpose are listed in `invalid_responses`; `stop()` fails the test if any are
left there, so a fake Service that built an invalid answer cannot go unnoticed.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from lxml import etree

from dod.domain.service import FaultKind
from dod.domain.v1 import (
    Announcement,
    ContentList,
    ContentMetadata,
    ContentResource,
    ServicePort,
)
from dod.infrastructure import HttpServicePort, validate_document

NS = "http://www.daisy.org/ns/daisy-online/"
BOOKMARK_NS = "http://www.daisy.org/z3986/2005/bookmark/"
SOAP = "http://schemas.xmlsoap.org/soap/envelope/"

_SERVICE_ATTRIBUTES = f"""\
<serviceAttributes xmlns="{NS}">
  <serviceProvider id="synthetic-provider"><label xml:lang="en"><text>Synthetic</text></label></serviceProvider>
  <service id="synthetic-service"><label xml:lang="en"><text>Synthetic service</text></label></service>
  <supportedContentSelectionMethods><method>BROWSE</method></supportedContentSelectionMethods>
  <supportsServerSideBack>false</supportsServerSideBack>
  <supportsSearch>false</supportsSearch>
  <supportedUplinkAudioCodecs/>
  <supportsAudioLabels>false</supportsAudioLabels>
  <supportedOptionalOperations/>
</serviceAttributes>
"""


@dataclass
class RecordedRequest:
    path: str
    headers: dict[str, str]
    body: bytes
    operation: str | None


@dataclass
class _Raw:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    # Seconds to wait before answering, and whether to hang up without answering.
    delay: float = 0.0
    drop: bool = False


_WSDL_NS = "http://schemas.xmlsoap.org/wsdl/"
_WSDL_SOAP = "http://schemas.xmlsoap.org/wsdl/soap/"


def service_wsdl(address: str, binding: str = "do:DaisyOnlineService") -> bytes:
    """A Service's own WSDL: it imports the abstract DODP WSDL and names one port."""
    return (
        f'<definitions xmlns="{_WSDL_NS}" xmlns:soap="{_WSDL_SOAP}" '
        f'xmlns:do="{NS}" targetNamespace="urn:synthetic:service">'
        f'<import namespace="{NS}" location="http://127.0.0.1:9/abstract.wsdl"/>'
        '<service name="SyntheticService">'
        f'<port name="SyntheticPort" binding="{binding}">'
        f'<soap:address location="{address}"/></port></service></definitions>'
    ).encode()


_INITIALISATION = {"getServiceAttributes", "setReadingSystemAttributes"}
_ALLOWED_BEFORE_INITIALISATION = _INITIALISATION | {"logOn", "logOff"}


def _envelope(inner: str) -> bytes:
    return (
        f'<soap:Envelope xmlns:soap="{SOAP}"><soap:Body>{inner}</soap:Body>'
        "</soap:Envelope>"
    ).encode()


class FakeService:
    """The Service and the controls the tests use to steer it."""

    def __init__(self) -> None:
        self.users: dict[str, str] = {}
        self.sessions: set[str] = set()
        # What each Session has done of the Initialisation sequence (4.2.1).
        self._initialised: dict[str, set[str]] = {}
        # A Service that refuses other operations before the Initialisation
        # sequence is complete (invalidOperation) is what the specification
        # requires; it is off here so that tests that skip the sequence on
        # purpose keep working.
        self.enforce_initialisation = False
        self.requests: list[RecordedRequest] = []
        # Plain GET requests (WSDL and anything else a client fetches).
        self.fetches: list[RecordedRequest] = []
        self.wsdl_path = "/dodp?wsdl"
        self.wsdl_body: bytes | None = None
        self.wsdl_redirect: str | None = None
        self.wsdl_delay = 0.0
        self.wsdl_address: str | None = None
        self.invalid_documents: list[str] = []
        self.invalid_responses: list[str] = []
        self.service_attributes_xml = _SERVICE_ATTRIBUTES
        # Bookmark sets by content id (none stored: an empty set), whether the
        # Service builds them schema-valid, and key exchange objects by key name.
        self.bookmarks: dict[str, str] = {}
        self._invalid_bookmarks: set[str] = set()
        self.key_exchange: dict[str, str] = {}
        # A Service that stores a different set than it was given.
        self.store_bookmarks_as: Callable[[str], str] | None = None
        self.announcements: list[Announcement] = []
        self.read_announcements: set[str] = set()
        self.lists: dict[str, ContentList] = {}
        self.metadata: dict[str, ContentMetadata] = {}
        # Books by content id: their resources and whether they are issued.
        self.books: dict[str, tuple[tuple[ContentResource, ...], bool]] = {}
        # Files served on plain GET by path (no leading slash), and exact answers.
        self.files: dict[str, bytes] = {}
        self.file_answers: dict[str, _Raw] = {}
        # A Service Delegate that does not support Range answers the whole file.
        self.ignore_range = False
        # The attributes of the Session cookie the Service sets on logOn.
        self.cookie_attributes = "Path=/; HttpOnly"
        self._injected: dict[str, tuple[FaultKind, str] | str | _Raw] = {}
        self._raw: _Raw | None = None
        self._deferred: dict[str, int] = {}
        self._delays: dict[str, float] = {}
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        handler = _make_handler(self)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}/dodp"

    @property
    def wsdl_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}{self.wsdl_path}"

    def stop(self) -> None:
        self._stopping.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        assert self.invalid_responses == [], (
            "the fake Service built a response that breaks the schemas: "
            f"{self.invalid_responses}"
        )

    # -- controls ---------------------------------------------------------

    def add_user(self, username: str, password: str) -> None:
        self.users[username] = password

    def offer_announcements(self, *announcements: Announcement) -> None:
        """Publish announcements and declare the two optional operations."""
        self.announcements = list(announcements)
        self.read_announcements = set()
        self.service_attributes_xml = self.service_attributes_xml.replace(
            "<supportedOptionalOperations/>",
            "<supportedOptionalOperations>"
            "<operation>SERVICE_ANNOUNCEMENTS</operation>"
            "</supportedOptionalOperations>",
        )

    def declare_operations(self, *tokens: str) -> None:
        """Declare optional operations in `supportedOptionalOperations`."""
        listed = "".join(f"<operation>{token}</operation>" for token in tokens)
        self.service_attributes_xml = self.service_attributes_xml.replace(
            "<supportedOptionalOperations/>",
            f"<supportedOptionalOperations>{listed}</supportedOptionalOperations>",
        )

    def offer_bookmarks(
        self, content_id: str, bookmark_set: str, *, schema_valid: bool = True
    ) -> None:
        """Store the bookmark set of a book; `schema_valid=False` is for a set
        that breaks the schema on purpose, answered as it is."""
        self.bookmarks[content_id] = bookmark_set
        if not schema_valid:
            self._invalid_bookmarks.add(content_id)

    def offer_key_exchange(self, key_name: str, key_exchange: str) -> None:
        """Answer `getKeyExchangeObject` for `key_name` with this element."""
        self.key_exchange[key_name] = key_exchange

    def offer_catalog(
        self, lists: Sequence[ContentList], metadata: Sequence[ContentMetadata]
    ) -> None:
        """Publish content lists by id and book metadata by identifier.

        A list id that is not an `xs:NMTOKEN` (it has whitespace, as some real
        menus have) is answered as it is, though the schemas reject it.
        """
        self.lists = {item.id: item for item in lists}
        self.metadata = {item.identifier or "": item for item in metadata}

    def offer_resources(
        self,
        content_id: str,
        resources: Sequence[ContentResource],
        *,
        issued: bool = True,
    ) -> None:
        """Publish the files of a book; unless `issued` they are not available."""
        self.books[content_id] = (tuple(resources), issued)

    def offer_file(self, path: str, body: bytes) -> None:
        """Serve `body` on GET of `/<path>`, with Range support."""
        self.files[path] = body

    def answer_file(
        self,
        path: str,
        status: int,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        """Answer GET of `/<path>` with exactly this."""
        self.file_answers[path] = _Raw(status, body, headers or {})

    def file_url(self, path: str) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}/{path}"

    def inject_fault(self, operation: str, kind: FaultKind | str, reason: str) -> None:
        """Answer the next `operation` with the DODP fault `kind` (HTTP 500)."""
        self._injected[operation] = (FaultKind(kind), reason)

    def inject_false(self, operation: str) -> None:
        """Answer the next `operation` with a result of `false`."""
        self._injected[operation] = "false"

    def inject_deviation(self, operation: str) -> None:
        self._injected[operation] = "deviation"

    def inject_http_500(self, operation: str) -> None:
        """Answer HTTP 500 with a SOAP fault that has no DODP fault element."""
        self._injected[operation] = _Raw(
            500,
            _envelope(
                "<soap:Fault><faultcode>soap:Server</faultcode>"
                "<faultstring>synthetic failure</faultstring></soap:Fault>"
            ),
        )

    def inject_not_soap(
        self, operation: str, body: bytes = b"<html><body>synthetic</body></html>"
    ) -> None:
        """Answer HTTP 200 with something that is not a SOAP envelope."""
        self._injected[operation] = _Raw(200, body, {"Content-Type": "text/html"})

    def inject_no_answer(self, operation: str) -> None:
        """Hang up on the next `operation` without answering at all."""
        self._injected[operation] = _Raw(0, b"", drop=True)

    def defer_injection(self, operation: str, calls: int) -> None:
        """Answer the next `calls` calls of `operation` normally before an
        injection for it fires, e.g. to get past the logon of a test's setup."""
        self._deferred[operation] = calls

    def inject_delay(self, operation: str, seconds: float) -> None:
        """Answer the next `operation` correctly, but only after `seconds`.

        Pair it with a client timeout shorter than `seconds`; `stop()` does not
        wait for the delay to run out.
        """
        self._delays[operation] = seconds

    def inject_redirect(self, operation: str, location: str, status: int = 307) -> None:
        """Answer the next `operation` with a redirect to `location`."""
        self._injected[operation] = _Raw(status, b"", {"Location": location})

    def respond_with(
        self, status: int, body: bytes, headers: dict[str, str] | None = None
    ) -> None:
        """Answer the next request with exactly this, whatever it asks for."""
        self._raw = _Raw(status, body, headers or {})

    def serve_wsdl(self, body: bytes) -> None:
        """Serve `body` instead of the generated WSDL."""
        self.wsdl_body = body

    def handle_get(self, path: str, headers: dict[str, str]) -> _Raw:
        with self._lock:
            self.fetches.append(RecordedRequest(path, headers, b"", None))
            served = self._file(path, headers)
            if served is not None:
                return served
            if path != self.wsdl_path:
                return _Raw(404, b"<html><body>not found</body></html>")
            raw = _Raw(
                200, self.wsdl_body or service_wsdl(self.wsdl_address or self.url)
            )
            if self.wsdl_redirect is not None:
                raw = _Raw(302, b"", {"Location": self.wsdl_redirect})
            raw.delay = self.wsdl_delay
            return raw

    def _file(self, path: str, headers: dict[str, str]) -> _Raw | None:
        name = path.removeprefix("/")
        if name in self.file_answers:
            return self.file_answers[name]
        body = self.files.get(name)
        if body is None:
            return None
        wanted = headers.get("Range", "")
        if not wanted.startswith("bytes=") or self.ignore_range:
            return _Raw(200, body, {"Content-Type": "application/octet-stream"})
        first, _, last = wanted.removeprefix("bytes=").partition("-")
        start = int(first)
        end = int(last) if last else len(body) - 1
        end = min(end, len(body) - 1)
        return _Raw(
            206,
            body[start : end + 1],
            {
                "Content-Type": "application/octet-stream",
                "Content-Range": f"bytes {start}-{end}/{len(body)}",
            },
        )

    # -- the Service itself -----------------------------------------------

    def handle(self, path: str, headers: dict[str, str], body: bytes) -> _Raw:
        with self._lock:
            raw = self._handle(path, headers, body)
            operation = self.requests[-1].operation
            raw.delay = self._delays.pop(operation or "", raw.delay)
            return raw

    def _handle(self, path: str, headers: dict[str, str], body: bytes) -> _Raw:
        operation = None
        try:
            root = etree.fromstring(body)
            payload = root.find(f"{{{SOAP}}}Body")[0]  # type: ignore[index]
            operation = etree.QName(payload).localname
            assert etree.QName(payload).namespace == NS
        except (etree.XMLSyntaxError, TypeError, IndexError, AssertionError):
            self.requests.append(RecordedRequest(path, headers, body, None))
            return _Raw(400, b"bad request")
        self.requests.append(RecordedRequest(path, headers, body, operation))
        if operation in {"setReadingSystemAttributes", "markAnnouncementsAsRead"}:
            child = etree.tostring(payload[0]).decode()
            if validate_document(child):
                self.invalid_documents.append(child)
        if operation == "setBookmarks":
            whole = etree.tostring(payload).decode()
            if validate_document(whole):
                self.invalid_documents.append(whole)
        if self._raw is not None:
            raw, self._raw = self._raw, None
            return raw
        if self._deferred.get(operation, 0) > 0 and operation in self._injected:
            self._deferred[operation] -= 1
            injected = None
        else:
            injected = self._injected.pop(operation, None)
        if injected == "false":
            return self._result(operation, False)
        if injected == "deviation":
            return _Raw(200, _envelope(f'<unexpected xmlns="{NS}"/>'))
        if isinstance(injected, _Raw):
            return injected
        if isinstance(injected, tuple):
            return self._fault(*injected)
        known = getattr(self, f"_op_{operation}", None)
        if known is None:
            if self._session(headers) is None:
                return self._no_session()
            return self._fault(FaultKind.INVALID_OPERATION, "unknown operation")
        if (
            self.enforce_initialisation
            and operation not in _ALLOWED_BEFORE_INITIALISATION
        ):
            token = self._session(headers)
            if token is not None and self._initialised.get(token) != _INITIALISATION:
                return self._fault(
                    FaultKind.INVALID_OPERATION,
                    "the initialisation sequence is not complete",
                )
        return known(payload, headers)  # type: ignore[no-any-return]

    def _initialising(self, headers: dict[str, str], step: str) -> None:
        token = self._session(headers)
        if token is not None:
            self._initialised.setdefault(token, set()).add(step)

    def _checked(self, document: str) -> None:
        """Record a document of ours that the local schemas do not accept."""
        if validate_document(document):
            self.invalid_responses.append(document)

    def _fault(self, kind: FaultKind, reason: str) -> _Raw:
        element = f'<{kind}Fault xmlns="{NS}"><reason>{reason}</reason></{kind}Fault>'
        self._checked(element)
        fault = (
            "<soap:Fault><faultcode>soap:Server</faultcode>"
            f"<faultstring>{reason}</faultstring><detail>{element}</detail>"
            "</soap:Fault>"
        )
        return _Raw(500, _envelope(fault))

    def _result(
        self, name: str, value: bool, extra: dict[str, str] | None = None
    ) -> _Raw:
        text = "true" if value else "false"
        xml = f'<{name}Response xmlns="{NS}"><{name}Result>{text}</{name}Result></{name}Response>'
        self._checked(xml)
        return _Raw(200, _envelope(xml), extra or {})

    def _session(self, headers: dict[str, str]) -> str | None:
        for part in headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "session" and value in self.sessions:
                return value
        return None

    def _no_session(self) -> _Raw:
        return self._fault(FaultKind.NO_ACTIVE_SESSION, "no active session")

    def _op_logOn(self, payload: Any, headers: dict[str, str]) -> _Raw:
        username = payload.findtext(f"{{{NS}}}username")
        password = payload.findtext(f"{{{NS}}}password")
        # Order matters on the wire: username before password.
        assert [etree.QName(c).localname for c in payload] == ["username", "password"]
        if username is None or self.users.get(username) != password:
            return self._result("logOn", False)
        token = secrets.token_hex(8)
        self.sessions.add(token)
        self._initialised[token] = set()
        return self._result(
            "logOn", True, {"Set-Cookie": f"session={token}; {self.cookie_attributes}"}
        )

    def _op_logOff(self, payload: Any, headers: dict[str, str]) -> _Raw:
        token = self._session(headers)
        self.sessions.discard(token or "")
        self._initialised.pop(token or "", None)
        return self._result("logOff", token is not None)

    def _op_getServiceAttributes(self, payload: Any, headers: dict[str, str]) -> _Raw:
        if self._session(headers) is None:
            return self._no_session()
        self._initialising(headers, "getServiceAttributes")
        xml = (
            f'<getServiceAttributesResponse xmlns="{NS}">'
            f"{self.service_attributes_xml.split('?>')[-1]}"
            "</getServiceAttributesResponse>"
        )
        self._checked(xml)
        return _Raw(200, _envelope(xml))

    def _op_setReadingSystemAttributes(
        self, payload: Any, headers: dict[str, str]
    ) -> _Raw:
        if self._session(headers) is None:
            return self._no_session()
        self._initialising(headers, "setReadingSystemAttributes")
        return self._result("setReadingSystemAttributes", True)

    def _op_getServiceAnnouncements(
        self, payload: Any, headers: dict[str, str]
    ) -> _Raw:
        if self._session(headers) is None:
            return self._no_session()
        if not self.announcements:
            return self._fault(FaultKind.OPERATION_NOT_SUPPORTED, "not supported")
        items = "".join(
            f'<announcement id="{a.id}" type="{a.type}" priority="{a.priority}">'
            f'<label xml:lang="{a.lang or "en"}"><text>{escape(a.text)}</text></label>'
            "</announcement>"
            for a in self.announcements
            if a.id not in self.read_announcements
        )
        xml = (
            f'<getServiceAnnouncementsResponse xmlns="{NS}">'
            f"<announcements>{items}</announcements>"
            "</getServiceAnnouncementsResponse>"
        )
        self._checked(xml)
        return _Raw(200, _envelope(xml))

    def _op_getContentList(self, payload: Any, headers: dict[str, str]) -> _Raw:
        if self._session(headers) is None:
            return self._no_session()
        # Order matters on the wire: id, firstItem, lastItem.
        assert [etree.QName(c).localname for c in payload] == [
            "id",
            "firstItem",
            "lastItem",
        ]
        wanted = payload.findtext(f"{{{NS}}}id") or ""
        try:
            first = int(payload.findtext(f"{{{NS}}}firstItem") or "0")
            last = int(payload.findtext(f"{{{NS}}}lastItem") or "-1")
        except ValueError:
            return self._fault(FaultKind.INVALID_PARAMETER, "not a number")
        known = self.lists.get(wanted)
        if known is None and wanted == "issued":
            known = ContentList(id="issued", total_items=0)
        if known is None:
            return self._fault(FaultKind.INVALID_PARAMETER, "unknown list")
        total = len(known.items)
        end = total - 1 if last == -1 else min(last, total - 1)
        valid = 0 <= first < total and first <= end
        shown = known.items[first : end + 1] if valid else ()
        attributes = f'totalItems="{known.total_items}" id="{escape(known.id)}"'
        if valid:
            attributes += f' firstItem="{first}" lastItem="{end}"'
        label = (
            f'<label xml:lang="en"><text>{escape(known.label)}</text></label>'
            if known.label
            else ""
        )
        items = "".join(
            f'<contentItem id="{escape(i.id)}"'
            + (f' lastModifiedDate="{i.last_modified}"' if i.last_modified else "")
            + f'><label xml:lang="{i.lang or "en"}"><text>{escape(i.label)}</text>'
            "</label></contentItem>"
            for i in shown
        )
        xml = (
            f'<getContentListResponse xmlns="{NS}">'
            f"<contentList {attributes}>{label}{items}</contentList>"
            "</getContentListResponse>"
        )
        if len(known.id.split()) == 1:
            self._checked(xml)
        return _Raw(200, _envelope(xml))

    def _op_getContentMetadata(self, payload: Any, headers: dict[str, str]) -> _Raw:
        if self._session(headers) is None:
            return self._no_session()
        known = self.metadata.get(payload.findtext(f"{{{NS}}}contentID") or "")
        if known is None:
            return self._fault(FaultKind.INVALID_PARAMETER, "unknown content")

        def dc(name: str, values: Sequence[str | None]) -> str:
            return "".join(
                f"<dc:{name}>{escape(value)}</dc:{name}>"
                for value in values
                if value is not None
            )

        body = (
            dc("title", [known.title])
            + dc("identifier", [known.identifier])
            + dc("publisher", [known.publisher])
            + dc("format", [known.format])
            + dc("date", [known.date])
            + dc("source", [known.source])
            + dc("type", known.types)
            + dc("subject", known.subjects)
            + dc("rights", known.rights)
            + dc("relation", known.relations)
            + dc("language", known.languages)
            + dc("description", known.descriptions)
            + dc("creator", known.creators)
            + dc("coverage", known.coverage)
            + dc("contributor", known.contributors)
            + "".join(f"<narrator>{escape(n)}</narrator>" for n in known.narrators)
            + f"<size>{known.size}</size>"
            + "".join(
                f'<meta name="{escape(n)}" content="{escape(c)}"/>'
                for n, c in known.meta
            )
        )
        sample = f'<sample id="{known.sample_id}"/>' if known.sample_id else ""
        category = f' category="{known.category}"' if known.category else ""
        returns = "true" if known.requires_return else "false"
        xml = (
            f'<getContentMetadataResponse xmlns="{NS}" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'<contentMetadata requiresReturn="{returns}"{category}>'
            f"{sample}<metadata>{body}</metadata></contentMetadata>"
            "</getContentMetadataResponse>"
        )
        self._checked(xml)
        return _Raw(200, _envelope(xml))

    def _op_getContentResources(self, payload: Any, headers: dict[str, str]) -> _Raw:
        if self._session(headers) is None:
            return self._no_session()
        known = self.books.get(payload.findtext(f"{{{NS}}}contentID") or "")
        if known is None or not known[1]:
            return self._fault(FaultKind.INVALID_PARAMETER, "content is not issued")
        items = "".join(
            f"<resource uri={quoteattr(r.uri)} mimeType={quoteattr(r.mime_type)} "
            f"size={quoteattr(str(r.size))} localURI={quoteattr(r.local_uri)}"
            + (
                f" lastModifiedDate={quoteattr(r.last_modified)}"
                if r.last_modified
                else ""
            )
            + "/>"
            for r in known[0]
        )
        xml = (
            f'<getContentResourcesResponse xmlns="{NS}">'
            f"<resources>{items}</resources></getContentResourcesResponse>"
        )
        self._checked(xml)
        return _Raw(200, _envelope(xml))

    def _op_issueContent(self, payload: Any, headers: dict[str, str]) -> _Raw:
        return self._lend("issueContent", payload, headers, issued=True)

    def _op_returnContent(self, payload: Any, headers: dict[str, str]) -> _Raw:
        return self._lend("returnContent", payload, headers, issued=False)

    def _lend(
        self, operation: str, payload: Any, headers: dict[str, str], *, issued: bool
    ) -> _Raw:
        if self._session(headers) is None:
            return self._no_session()
        wanted = payload.findtext(f"{{{NS}}}contentID") or ""
        if wanted not in self.books and wanted not in self.metadata:
            return self._fault(FaultKind.INVALID_PARAMETER, "unknown content")
        files = self.books.get(wanted, ((), issued))[0]
        self.books[wanted] = (files, issued)
        return self._result(operation, True)

    def _known(self, content_id: str) -> bool:
        return content_id in self.books or content_id in self.metadata

    def _op_getBookmarks(self, payload: Any, headers: dict[str, str]) -> _Raw:
        if self._session(headers) is None:
            return self._no_session()
        wanted = payload.findtext(f"{{{NS}}}contentID") or ""
        if not self._known(wanted):
            return self._fault(FaultKind.INVALID_PARAMETER, "unknown content")
        stored = self.bookmarks.get(wanted) or (
            f'<bookmarkSet xmlns="{BOOKMARK_NS}"><title><text/></title>'
            f"<uid>{escape(wanted)}</uid></bookmarkSet>"
        )
        xml = f'<getBookmarksResponse xmlns="{NS}">{stored}</getBookmarksResponse>'
        if wanted not in self._invalid_bookmarks:
            self._checked(xml)
        return _Raw(200, _envelope(xml))

    def _op_setBookmarks(self, payload: Any, headers: dict[str, str]) -> _Raw:
        if self._session(headers) is None:
            return self._no_session()
        wanted = payload.findtext(f"{{{NS}}}contentID") or ""
        if not self._known(wanted):
            return self._fault(FaultKind.INVALID_PARAMETER, "unknown content")
        stored = payload.find(f"{{{BOOKMARK_NS}}}bookmarkSet")
        if stored is None or stored.findtext(f"{{{BOOKMARK_NS}}}uid") != wanted:
            return self._fault(FaultKind.INVALID_PARAMETER, "the uid is not the id")
        text = etree.tostring(stored).decode()
        self.bookmarks[wanted] = (
            self.store_bookmarks_as(text) if self.store_bookmarks_as else text
        )
        self._invalid_bookmarks.discard(wanted)
        return self._result("setBookmarks", True)

    def _op_getKeyExchangeObject(self, payload: Any, headers: dict[str, str]) -> _Raw:
        if self._session(headers) is None:
            return self._no_session()
        name = payload.findtext(f"{{{NS}}}requestedKeyName") or ""
        if name not in self.key_exchange:
            return self._fault(FaultKind.INVALID_PARAMETER, "unknown key")
        xml = (
            f'<getKeyExchangeObjectResponse xmlns="{NS}">'
            f"{self.key_exchange[name]}</getKeyExchangeObjectResponse>"
        )
        self._checked(xml)
        return _Raw(200, _envelope(xml))

    def _op_markAnnouncementsAsRead(
        self, payload: Any, headers: dict[str, str]
    ) -> _Raw:
        if self._session(headers) is None:
            return self._no_session()
        if not self.announcements:
            return self._fault(FaultKind.OPERATION_NOT_SUPPORTED, "not supported")
        ids = [(item.text or "") for item in payload.iter(f"{{{NS}}}item")]
        if not set(ids) <= {a.id for a in self.announcements}:
            return self._fault(FaultKind.INVALID_PARAMETER, "unknown announcement")
        fresh = set(ids) - self.read_announcements
        self.read_announcements |= fresh
        return self._result("markAnnouncementsAsRead", bool(fresh))


def _make_handler(service: FakeService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            headers = {key: value for key, value in self.headers.items()}
            self._answer(service.handle_get(self.path, headers))

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            headers = {key: value for key, value in self.headers.items()}
            self._answer(service.handle(self.path, headers, body))

        def _answer(self, raw: _Raw) -> None:
            if raw.delay:
                service._stopping.wait(raw.delay)
            if raw.drop or service._stopping.is_set():
                self.close_connection = True
                return
            self.send_response(raw.status)
            headers_out = {"Content-Type": "text/xml; charset=utf-8", **raw.headers}
            for key, value in headers_out.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(raw.body)))
            self.end_headers()
            self.wfile.write(raw.body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


class HttpHarness:
    """The contract `Harness` for the HTTP adapter against a `FakeService`."""

    def __init__(self) -> None:
        self.service = FakeService()
        self._ports: list[ServicePort] = []

    def add_user(self, username: str, password: str) -> None:
        self.service.add_user(username, password)

    def inject_fault(self, operation: str, kind: str, reason: str) -> None:
        self.service.inject_fault(operation, kind, reason)

    def inject_deviation(self, operation: str) -> None:
        self.service.inject_deviation(operation)

    def inject_false(self, operation: str) -> None:
        self.service.inject_false(operation)

    def offer_announcements(self, *announcements: Announcement) -> None:
        self.service.offer_announcements(*announcements)

    def declare_operations(self, *tokens: str) -> None:
        self.service.declare_operations(*tokens)

    def offer_bookmarks(
        self, content_id: str, bookmark_set: str, *, schema_valid: bool = True
    ) -> None:
        self.service.offer_bookmarks(
            content_id, bookmark_set, schema_valid=schema_valid
        )

    def offer_key_exchange(self, key_name: str, key_exchange: str) -> None:
        self.service.offer_key_exchange(key_name, key_exchange)

    def offer_catalog(
        self, lists: Sequence[ContentList], metadata: Sequence[ContentMetadata]
    ) -> None:
        self.service.offer_catalog(lists, metadata)

    def offer_resources(
        self,
        content_id: str,
        resources: Sequence[ContentResource],
        *,
        issued: bool = True,
    ) -> None:
        self.service.offer_resources(content_id, resources, issued=issued)

    def offer_file(self, path: str, body: bytes) -> None:
        self.service.offer_file(path, body)

    def file_url(self, path: str) -> str:
        return self.service.file_url(path)

    def open_port(self) -> ServicePort:
        port = HttpServicePort(self.service.url)
        self._ports.append(port)
        return port

    def close(self) -> None:
        for port in self._ports:
            port.close()
        self.service.stop()
