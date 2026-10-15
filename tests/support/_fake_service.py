"""A minimal DODP v1 Service on localhost, for the tests only (ADR 0003).

It speaks SOAP 1.1 document/literal over HTTP, validates every request and
every response document against the local schema copies and records what it
received. Faults and deviations are injected per operation and used once.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from lxml import etree

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
        self.service_attributes_xml = _SERVICE_ATTRIBUTES
        self.allow_invalid_attributes = False
        self._injected: dict[str, tuple[str, str] | str] = {}
        self._raw: _Raw | None = None
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
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    # -- controls ---------------------------------------------------------

    def add_user(self, username: str, password: str) -> None:
        self.users[username] = password

    def inject_fault(self, operation: str, kind: str, reason: str) -> None:
        self._injected[operation] = (kind, reason)

    def inject_deviation(self, operation: str) -> None:
        self._injected[operation] = "deviation"

    def respond_with(
        self, status: int, body: bytes, headers: dict[str, str] | None = None
    ) -> None:
        """Answer the next request with exactly this, whatever it asks for."""
        self._raw = _Raw(status, body, headers or {})

    # -- the Service itself -----------------------------------------------

    def handle(self, path: str, headers: dict[str, str], body: bytes) -> _Raw:
        with self._lock:
            return self._handle(path, headers, body)

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
        if isinstance(injected, tuple):
            kind, reason = injected
            fault = (
                f"<soap:Fault><faultcode>soap:Server</faultcode>"
                f"<faultstring>{reason}</faultstring><detail>"
                f'<{kind}Fault xmlns="{NS}"><reason>{reason}</reason></{kind}Fault>'
                f"</detail></soap:Fault>"
            )
            return _Raw(500, _envelope(fault))
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

    def _result(
        self, name: str, value: bool, extra: dict[str, str] | None = None
    ) -> _Raw:
        text = "true" if value else "false"
        xml = f'<{name}Response xmlns="{NS}"><{name}Result>{text}</{name}Result></{name}Response>'
        return _Raw(200, _envelope(xml), extra or {})

    def _session(self, headers: dict[str, str]) -> str | None:
        for part in headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "session" and value in self.sessions:
                return value
        return None

    def _no_session(self) -> _Raw:
        fault = (
            "<soap:Fault><faultcode>soap:Server</faultcode>"
            "<faultstring>no active session</faultstring><detail>"
            f'<noActiveSessionFault xmlns="{NS}"><reason>no active session</reason>'
            "</noActiveSessionFault></detail></soap:Fault>"
        )
        return _Raw(500, _envelope(fault))

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
        if (
            validate_document(self.service_attributes_xml)
            and not self.allow_invalid_attributes
        ):
            raise AssertionError("the fake Service built an invalid document")
        xml = (
            f'<getServiceAttributesResponse xmlns="{NS}">'
            f"{self.service_attributes_xml.split('?>')[-1]}"
            "</getServiceAttributesResponse>"
        )
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
