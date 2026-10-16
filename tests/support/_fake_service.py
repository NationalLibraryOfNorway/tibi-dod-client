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
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from lxml import etree

from dod.domain.service import FaultKind
from dod.domain.v1 import ServicePort
from dod.infrastructure import HttpServicePort, validate_document

NS = "http://www.daisy.org/ns/daisy-online/"
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
        self.requests: list[RecordedRequest] = []
        self.invalid_documents: list[str] = []
        self.invalid_responses: list[str] = []
        self.service_attributes_xml = _SERVICE_ATTRIBUTES
        self._injected: dict[str, tuple[FaultKind, str] | str | _Raw] = {}
        self._raw: _Raw | None = None
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

    def inject_fault(self, operation: str, kind: FaultKind | str, reason: str) -> None:
        """Answer the next `operation` with the DODP fault `kind` (HTTP 500)."""
        self._injected[operation] = (FaultKind(kind), reason)

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
        if operation == "setReadingSystemAttributes":
            child = etree.tostring(payload[0]).decode()
            if validate_document(child):
                self.invalid_documents.append(child)
        if self._raw is not None:
            raw, self._raw = self._raw, None
            return raw
        injected = self._injected.pop(operation, None)
        if injected == "deviation":
            return _Raw(200, _envelope(f'<unexpected xmlns="{NS}"/>'))
        if isinstance(injected, _Raw):
            return injected
        if isinstance(injected, tuple):
            return self._fault(*injected)
        return getattr(self, f"_op_{operation}", self._unknown)(payload, headers)

    def _unknown(self, payload: Any, headers: dict[str, str]) -> _Raw:
        return _Raw(
            500,
            _envelope(
                "<soap:Fault><faultcode>soap:Client</faultcode>"
                "<faultstring>unknown operation</faultstring>"
                "</soap:Fault>"
            ),
        )

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
        return self._result(
            "logOn", True, {"Set-Cookie": f"session={token}; Path=/; HttpOnly"}
        )

    def _op_logOff(self, payload: Any, headers: dict[str, str]) -> _Raw:
        token = self._session(headers)
        self.sessions.discard(token or "")
        return self._result("logOff", token is not None)

    def _op_getServiceAttributes(self, payload: Any, headers: dict[str, str]) -> _Raw:
        if self._session(headers) is None:
            return self._no_session()
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
        return self._result("setReadingSystemAttributes", True)


def _make_handler(service: FakeService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            headers = {key: value for key, value in self.headers.items()}
            raw = service.handle(self.path, headers, body)
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

    def open_port(self) -> ServicePort:
        port = HttpServicePort(self.service.url)
        self._ports.append(port)
        return port

    def close(self) -> None:
        for port in self._ports:
            port.close()
        self.service.stop()
